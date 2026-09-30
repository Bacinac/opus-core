import asyncio

import httpx
import pytest

from opus_core import dida

CONFIG = {"dida_url": "http://dida.test", "dida_username": "opus", "dida_password": "secret"}


class Dida:
    def __init__(self):
        self.logins = []
        self.made = []
        self.valid = set()
        self.refuse_everything = False
        self.commands = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/auth/"):
            self.logins.append(request.url.path)
            await asyncio.sleep(0.05)
            cookie = f"session-{len(self.logins)}"
            self.valid = {cookie}
            return httpx.Response(200, json={"ok": True},
                                  headers={"Set-Cookie": f"dida_session={cookie}; Path=/"})
        sent = request.headers.get("cookie", "").removeprefix("dida_session=")
        if self.refuse_everything or sent not in self.valid:
            return httpx.Response(401)
        if request.url.path == "/api/contacts/person":
            return httpx.Response(200, json={"born_on": "2010-06-15"})
        if request.url.path == "/api/command":
            self.commands.append(request.read())
            return httpx.Response(204)
        if request.url.path == "/api/camera/door/snapshot":
            return httpx.Response(200, content=b"jpeg", headers={"Content-Type": "image/jpeg"})
        if request.url.path == "/api/camera/door/mjpeg":
            return httpx.Response(200, content=b"frame" * 3,
                                  headers={"Content-Type": "multipart/x-mixed-replace"})
        if request.url.path == "/api/broken":
            return httpx.Response(500)
        return httpx.Response(404)


@pytest.fixture
def house(monkeypatch):
    service = Dida()
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(service))
        service.made.append(real(*args, **kwargs))
        return service.made[-1]

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(dida, "_lock", asyncio.Lock())
    yield service
    asyncio.run(dida.close())


def ask(coroutine):
    async def closing():
        try:
            return await coroutine
        finally:
            await dida.close()
    return asyncio.run(closing())


def person(config=CONFIG):
    return dida.call(config, "GET", "/api/contacts/person", params={"name": "Kata"})


def test_a_crowd_of_requests_shares_one_client_and_one_login(house):
    async def crowd():
        return await asyncio.gather(*(person() for _ in range(6)))

    assert ask(crowd()) == [{"born_on": "2010-06-15"}] * 6
    assert (len(house.logins), len(house.made)) == (1, 1)


def test_an_expired_session_is_renewed_once_for_everyone_refused_with_it(house):
    async def scenario():
        await person()
        house.valid = set()
        return await asyncio.gather(*(person() for _ in range(5)))

    assert ask(scenario()) == [{"born_on": "2010-06-15"}] * 5
    assert len(house.logins) == 2


def test_a_session_refused_again_after_logging_in_is_an_error(house):
    house.refuse_everything = True
    with pytest.raises(dida.DidaError):
        ask(person())
    assert len(house.logins) == 2


def test_a_machine_logs_in_with_the_panel_key(house):
    panel = {"dida_url": "http://dida.test", "dida_panel_key": "k"}
    assert ask(person(panel)) == {"born_on": "2010-06-15"}
    assert house.logins == ["/api/auth/panel"]


@pytest.mark.parametrize("config", [
    {"dida_url": ""},
    {"dida_url": "http://dida.test", "dida_username": "", "dida_password": "", "dida_panel_key": ""},
])
def test_an_unconfigured_house_is_said(house, config):
    with pytest.raises(dida.DidaError):
        ask(person(config))


def test_nothing_at_an_address_is_told_apart_from_a_failure(house):
    with pytest.raises(dida.Absent):
        ask(dida.call(CONFIG, "GET", "/api/nowhere"))
    with pytest.raises(dida.DidaError) as failed:
        ask(dida.call(CONFIG, "GET", "/api/broken"))
    assert not isinstance(failed.value, dida.Absent)


def test_a_command_is_sent_as_json_and_an_empty_answer_is_empty(house):
    said = ask(dida.call(CONFIG, "POST", "/api/command", json={"entity_id": "tv"}))
    assert said == {} and house.commands == [b'{"entity_id":"tv"}']


def test_media_comes_back_with_its_type(house):
    assert ask(dida.content(CONFIG, "/api/camera/door/snapshot")) == (b"jpeg", "image/jpeg")

    async def watch():
        body, kind = await dida.stream(CONFIG, "/api/camera/door/mjpeg")
        return b"".join([chunk async for chunk in body]), kind

    assert ask(watch()) == (b"frame" * 3, "multipart/x-mixed-replace")


def test_a_refused_stream_closes_its_own_client(house):
    with pytest.raises(dida.Absent):
        ask(dida.stream(CONFIG, "/api/camera/hall/mjpeg"))
    assert len(house.made) == 2 and all(http.is_closed for http in house.made)


def test_a_new_address_closes_the_old_client(house):
    moved = {**CONFIG, "dida_url": "http://dida-2.test"}

    async def scenario():
        await person()
        old = dida._clients["http://dida.test"]
        await person(moved)
        return old.is_closed, list(dida._clients)

    assert ask(scenario()) == (True, ["http://dida-2.test"])
