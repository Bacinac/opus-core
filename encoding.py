"""JSON answers compressed for whoever accepts it.

Only JSON, and only a whole JSON body: a film, an original photograph or a
range of either is already as small as it gets and goes out byte for byte as it
streams, so nothing else is ever held back here."""

import asyncio
import gzip
from compression import zstd

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# below this the saving is smaller than the headers that announce it
MINIMUM = 1024
# compressing more than this takes long enough to hold up every other request
# on the event loop, so it goes to a thread; zlib and zstd let go of the GIL
IN_THREAD = 64 * 1024


def accepted(header: str) -> str | None:
    """zstd where the client takes it — smaller and faster than gzip — else gzip."""
    weights: dict[str, float] = {}
    for part in header.split(","):
        coding, *params = part.split(";")
        weight = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip() == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        weights[coding.strip().lower()] = weight
    for coding in ("zstd", "gzip"):
        if weights.get(coding, weights.get("*", 0.0)) > 0:
            return coding
    return None


def _compressible(status: int, headers: Headers) -> bool:
    kind = headers.get("content-type", "").split(";")[0].strip().lower()
    return ((kind == "application/json" or kind.endswith("+json"))
            and status not in (204, 304)
            and "content-encoding" not in headers
            and "no-transform" not in headers.get("cache-control", ""))


def _compress(coding: str, body: bytes) -> bytes:
    if coding == "zstd":
        return zstd.compress(body)
    return gzip.compress(body, mtime=0)


class CompressJSON:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        coding = accepted(Headers(scope=scope).get("accept-encoding", "")) \
            if scope["type"] == "http" else None
        if coding is None:
            await self.app(scope, receive, send)
            return

        held: Message | None = None

        async def answer(message: Message) -> None:
            nonlocal held
            if message["type"] == "http.response.start":
                if _compressible(message["status"], Headers(raw=message["headers"])):
                    held = message
                else:
                    await send(message)
                return
            if held is None:
                await send(message)
                return
            start, held = held, None
            body = message.get("body", b"")
            if message.get("more_body") or len(body) < MINIMUM:
                await send(start)
                await send(message)
                return
            packed = (await asyncio.to_thread(_compress, coding, body)
                      if len(body) > IN_THREAD else _compress(coding, body))
            headers = MutableHeaders(raw=list(start["headers"]))
            headers["content-encoding"] = coding
            headers["content-length"] = str(len(packed))
            headers.add_vary_header("Accept-Encoding")
            etag = headers.get("etag")
            if etag and not etag.startswith("W/"):
                headers["etag"] = f"W/{etag}"
            await send({**start, "headers": headers.raw})
            await send({"type": "http.response.body", "body": packed})

        await self.app(scope, receive, answer)
