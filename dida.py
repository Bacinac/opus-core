"""The client for DIDA, the house's automation.

How a module reaches DIDA is the same everywhere: one door, by whichever
credential is configured, and one session renewed once when DIDA refuses it.
What a module asks DIDA is its own and stays with it.

`config` is the module's settings as one read saw them: anything whose
`get(key)` answers `dida_url` and the credentials."""

import asyncio
from collections.abc import AsyncIterator

import httpx


class DidaError(Exception):
    """DIDA could not be reached or refused. Never swallowed."""


class Absent(DidaError):
    """DIDA has nothing at that address."""


# One client and one session per configured install, shared across requests:
# logging in per request would hammer DIDA's login rate limit and its argon2
# verify, and a connection per request is two new sockets every poll.
_clients: dict[str, httpx.AsyncClient] = {}
_cookies: dict[str, str] = {}
_lock = asyncio.Lock()


def _base(config) -> str:
    url = (config.get("dida_url") or "").rstrip("/")
    if not url:
        raise DidaError("no dida url is configured")
    return url


async def _client(base: str) -> httpx.AsyncClient:
    http = _clients.get(base)
    if http is None or http.is_closed:
        for old in [b for b in _clients if b != base]:
            _cookies.pop(old, None)
            await _clients.pop(old).aclose()
        _clients[base] = http = httpx.AsyncClient(base_url=base, timeout=10)
    return http


async def close() -> None:
    while _clients:
        _, http = _clients.popitem()
        await http.aclose()
    _cookies.clear()


async def _login(config, http: httpx.AsyncClient) -> str:
    """A session, by whichever door is configured: a user of DIDA's own, or the
    stable panel key DIDA already issues for machines that cannot type."""
    user = config.get("dida_username")
    secret = config.get("dida_password")
    key = config.get("dida_panel_key")
    if user and secret:
        resp = await http.post("/api/auth/login",
                               json={"username": user, "password": secret})
    elif key:
        resp = await http.post("/api/auth/panel", json={"k": key})
    else:
        raise DidaError("dida credentials are not configured")
    if resp.status_code != 200:
        raise DidaError(f"dida refused the login ({resp.status_code})")
    cookie = resp.cookies.get("dida_session")
    if not cookie:
        raise DidaError("dida answered the login without a session")
    return cookie


async def _session(config, http: httpx.AsyncClient, base: str, stale: str | None = None) -> str:
    """The session to send, logging in only when there is none or the one that
    was refused is still the one held: several requests refused together log in
    once, and the rest take what the first one got."""
    async with _lock:
        cookie = _cookies.get(base)
        if cookie is None or cookie == stale:
            cookie = _cookies[base] = await _login(config, http)
        return cookie


async def _send(config, method: str, path: str, *, via: httpx.AsyncClient | None = None,
                stream: bool = False, **request) -> httpx.Response:
    base = _base(config)
    try:
        http = await _client(base)
        via = via or http

        async def attempt(cookie: str) -> httpx.Response:
            return await via.send(via.build_request(
                method, path, headers={"Cookie": f"dida_session={cookie}"}, **request),
                stream=stream)

        cookie = await _session(config, http, base)
        resp = await attempt(cookie)
        if resp.status_code == 401:
            # the session died with a password change or a token bump; prove
            # ourselves once more and repeat the request
            await resp.aclose()
            cookie = await _session(config, http, base, stale=cookie)
            resp = await attempt(cookie)
    except httpx.HTTPError as exc:
        raise DidaError(f"dida {path} failed: {exc}") from exc
    if resp.status_code >= 400:
        await resp.aclose()
        refused = Absent if resp.status_code == 404 else DidaError
        raise refused(f"dida {path} failed: {resp.status_code}")
    return resp


async def call(config, method: str, path: str, *, params: dict | None = None,
               json: dict | None = None) -> dict | list:
    resp = await _send(config, method, path, params=params, json=json)
    return resp.json() if resp.content else {}


async def content(config, path: str) -> tuple[bytes, str]:
    """Authenticated bytes from a DIDA media route, without exposing its secret."""
    resp = await _send(config, "GET", path)
    return resp.content, resp.headers.get("content-type", "application/octet-stream")


async def stream(config, path: str) -> tuple[AsyncIterator[bytes], str]:
    """An authenticated body kept streaming until its reader leaves, on a client
    of its own with no read timeout: a camera sends for as long as it is watched."""
    media = httpx.AsyncClient(base_url=_base(config), timeout=httpx.Timeout(None, connect=10.0))
    try:
        resp = await _send(config, "GET", path, via=media, stream=True)
    except BaseException:
        await media.aclose()
        raise

    async def body():
        try:
            async for chunk in resp.aiter_bytes(65536):
                yield chunk
        finally:
            await resp.aclose()
            await media.aclose()

    return body(), resp.headers.get("content-type", "application/octet-stream")
