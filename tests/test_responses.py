import anyio

from opus_core.responses import FileResponse


def _scope(range_header: bytes | None = None) -> dict:
    headers = [(b"range", range_header)] if range_header else []
    return {"type": "http", "method": "GET", "path": "/", "headers": headers,
            "asgi": {"version": "3.0", "spec_version": "2.3"}}


def test_a_client_that_hangs_up_stops_the_reading(tmp_path):
    film = tmp_path / "film.mkv"
    film.write_bytes(b"\0" * (64 * 1024 * 1024))
    sent = []

    async def main():
        gone = anyio.Event()

        async def receive():
            await gone.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            # uvicorn discards a send after the connection is gone rather than failing it
            if message["type"] == "http.response.body":
                sent.append(len(message["body"]))
                if len(sent) == 3:
                    gone.set()
            await anyio.sleep(0)

        with anyio.fail_after(5):
            await FileResponse(film)(_scope(b"bytes=0-"), receive, send)

    anyio.run(main)
    assert sum(sent) < film.stat().st_size // 4


def test_a_client_that_stays_gets_the_whole_range(tmp_path):
    film = tmp_path / "film.mkv"
    film.write_bytes(bytes(range(256)) * 4096)
    body = bytearray()

    async def main():
        async def receive():
            await anyio.sleep_forever()

        async def send(message):
            if message["type"] == "http.response.body":
                body.extend(message["body"])

        with anyio.fail_after(5):
            await FileResponse(film)(_scope(b"bytes=1000-"), receive, send)

    anyio.run(main)
    assert bytes(body) == film.read_bytes()[1000:]
