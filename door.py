"""The door every request to a module passes, as plain ASGI.

A module says why a request may not pass: `refusal(request)` returns the answer
to give instead, or None to let it through. `@app.middleware("http")` would run
the same function inside Starlette's BaseHTTPMiddleware, which sends every
answer on as a stream of chunks; CompressJSON takes a stream for a stream and
leaves it alone, so behind that no JSON answer was ever compressed."""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

Refusal = Callable[[Request], Awaitable[Response | None]]


class Door:
    def __init__(self, app: ASGIApp, refusal: Refusal):
        self.app = app
        self.refusal = refusal

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            refused = await self.refusal(Request(scope, receive))
            if refused is not None:
                await refused(scope, receive, send)
                return
        await self.app(scope, receive, send)
