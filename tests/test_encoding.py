import asyncio
import gzip
import json
from compression import zstd

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from opus_core.encoding import CompressJSON, accepted

ARTISTS = [{"id": n, "name": f"Artist {n}", "sort": f"artist {n:05d}"} for n in range(400)]


async def artists(request):
    return JSONResponse(ARTISTS, headers={"ETag": '"v1"'})


async def small(request):
    return JSONResponse({"ok": True})


async def film(request):
    async def chunks():
        yield b"\x00" * 4096
        yield b"\x01" * 4096
    return StreamingResponse(chunks(), status_code=206, media_type="video/mp4",
                             headers={"Content-Range": "bytes 0-8191/99999"})


async def packed(request):
    return Response(gzip.compress(json.dumps(ARTISTS).encode()), media_type="application/json",
                    headers={"Content-Encoding": "gzip"})


async def lines(request):
    async def chunks():
        for artist in ARTISTS:
            yield json.dumps(artist).encode() + b"\n"
    return StreamingResponse(chunks(), media_type="application/json")


APP = Starlette(routes=[Route(f"/{f.__name__}", f, methods=["GET", "HEAD"])
                        for f in (artists, small, film, packed, lines)])


def served(path: str, accept: str | None, app=None, method: str = "GET"):
    sent = []
    headers = [(b"accept-encoding", accept.encode())] if accept is not None else []
    scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": headers, "scheme": "http", "http_version": "1.1",
             "server": ("test", 80), "client": ("127.0.0.1", 1), "root_path": ""}

    asked = []

    async def receive():
        if asked:
            await asyncio.Event().wait()
        asked.append(True)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run((app or CompressJSON(APP))(scope, receive, send))
    start = sent[0]
    return ({k.decode(): v.decode() for k, v in start["headers"]},
            b"".join(m.get("body", b"") for m in sent[1:]), sent)


@pytest.mark.parametrize(("header", "coding"), [
    ("gzip, deflate, br, zstd", "zstd"),
    ("gzip, deflate", "gzip"),
    ("*", "zstd"),
    ("zstd;q=0, gzip;q=0.5", "gzip"),
    ("identity", None),
    ("gzip;q=0", None),
    ("", None),
])
def test_the_coding_is_what_the_client_takes(header, coding):
    assert accepted(header) == coding


@pytest.mark.parametrize(("accept", "unpack"), [
    ("gzip, deflate, br, zstd", zstd.decompress),
    ("gzip, deflate", gzip.decompress),
])
def test_a_json_answer_goes_out_compressed(accept, unpack):
    headers, body, _ = served("/artists", accept)
    assert json.loads(unpack(body)) == ARTISTS
    assert headers["content-length"] == str(len(body))
    assert headers["content-encoding"] in accept
    assert headers["vary"] == "Accept-Encoding"
    assert len(body) * 5 < len(json.dumps(ARTISTS))


def test_a_strong_etag_is_weak_once_the_bytes_differ():
    assert served("/artists", "gzip")[0]["etag"] == 'W/"v1"'


@pytest.mark.parametrize("path", ["/film", "/packed", "/lines", "/small"])
def test_everything_else_goes_out_exactly_as_it_was_made(path):
    assert served(path, "gzip, zstd")[2] == served(path, "gzip, zstd", app=APP)[2]


def test_a_client_that_takes_nothing_gets_the_json_as_it_was_made():
    assert served("/artists", None)[2] == served("/artists", None, app=APP)[2]


def test_a_head_request_is_told_what_the_get_would_get():
    assert served("/artists", "gzip", method="HEAD")[0] == served("/artists", "gzip")[0]
