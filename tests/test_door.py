import json
from compression import zstd

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from opus_core.door import Door
from opus_core.encoding import CompressJSON
from opus_core.tests.test_encoding import ARTISTS, served


async def refusal(request):
    if request.headers.get("accept-encoding") == "refuse":
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    request.state.seen = "at the door"
    return None


async def artists(request):
    return JSONResponse(ARTISTS)


async def state(request):
    return JSONResponse({"seen": request.state.seen, "pad": "x" * 2048})


ROUTES = [Route("/artists", artists), Route("/state", state)]


def module(*middleware):
    return CompressJSON(Starlette(routes=ROUTES, middleware=list(middleware)))


DOOR = module(Middleware(Door, refusal=refusal))


def test_a_refused_request_is_answered_at_the_door():
    headers, body, _ = served("/artists", "refuse", app=DOOR)
    assert json.loads(body) == {"detail": "authentication required"}


def test_what_the_door_notes_reaches_the_route():
    _, body, _ = served("/state", "zstd", app=DOOR)
    assert json.loads(zstd.decompress(body))["seen"] == "at the door"


def test_behind_the_door_a_json_answer_goes_out_compressed():
    headers, body, _ = served("/artists", "zstd", app=DOOR)
    assert headers["content-encoding"] == "zstd"
    assert json.loads(zstd.decompress(body)) == ARTISTS

