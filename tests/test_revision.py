import json

from fastapi import FastAPI

from opus_core.revision import router
from opus_core.tests.test_encoding import served

STAMP = {
    "version": "0.1.650",
    "sha": "c0ae961a",
    "branch": "main",
    "committed_at": "2026-09-26T05:14:31+02:00",
    "dirty": False,
}


def module(stamp):
    app = FastAPI()
    app.include_router(router("opus-library", stamp), prefix="/api")
    return app


def asked(app):
    _, body, sent = served("/api/version", None, app)
    return sent[0]["status"], json.loads(body)


def test_the_stamp_is_said_with_the_module_it_belongs_to(tmp_path):
    stamp = tmp_path / "revision.json"
    stamp.write_text(json.dumps(STAMP))
    assert asked(module(stamp)) == (200, {"product": "opus-library", **STAMP})


def test_a_new_stamp_is_what_the_next_answer_says(tmp_path):
    stamp = tmp_path / "revision.json"
    stamp.write_text(json.dumps(STAMP))
    app = module(stamp)
    asked(app)
    stamp.write_text(json.dumps({**STAMP, "version": "0.1.651"}))
    assert asked(app)[1]["version"] == "0.1.651"


def test_a_build_without_a_stamp_says_so(tmp_path):
    assert asked(module(tmp_path / "revision.json")) == (404, {"detail": "this build carries no revision stamp"})
