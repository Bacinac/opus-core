import json
import sys

import pytest
from fastapi import FastAPI

from opus_core import plugins
from opus_core.tests.test_encoding import served


def plugin(root, name, manifest, code=""):
    directory = root / name
    (directory / f"{name}_code").mkdir(parents=True)
    (directory / f"{name}_code" / "__init__.py").write_text(code)
    (directory / plugins.MANIFEST).write_text(manifest)
    return directory


@pytest.fixture(autouse=True)
def forget_imports():
    before = set(sys.modules), list(sys.path)
    yield
    plugins.resolve.cache_clear()
    for name in set(sys.modules) - before[0]:
        del sys.modules[name]
    sys.path[:] = before[1]


def test_an_installation_without_plugins_loads_nothing(tmp_path):
    assert plugins.load("opus-library", tmp_path) == ()
    assert plugins.load("opus-library", tmp_path / "absent") == ()


def test_each_module_gets_only_what_is_named_for_it(tmp_path):
    plugin(tmp_path, "one", '[modules]\nopus-library = "one_code:HOOK"\n', "HOOK = 'library'\n")
    plugin(tmp_path, "two", '[modules]\nopus-player = "two_code:HOOK"\n', "HOOK = 'player'\n")
    assert plugins.load("opus-library", tmp_path) == ("library",)
    assert plugins.load("opus-player", tmp_path) == ("player",)
    assert plugins.load("opus-downloads", tmp_path) == ()


def test_a_plugin_that_does_not_load_stops_the_start(tmp_path):
    plugin(tmp_path, "broken", '[modules]\nopus-library = "broken_code:MISSING"\n')
    with pytest.raises(plugins.PluginError, match="broken"):
        plugins.load("opus-library", tmp_path)
    (tmp_path / "broken" / plugins.MANIFEST).write_text("modules = [")
    with pytest.raises(plugins.PluginError, match="unreadable"):
        plugins.load("opus-library", tmp_path)


class Said:
    def __init__(self, words):
        self.words = words


def test_words_are_merged_and_served():
    first = Said({"hr": {"engine.x": "X"}, "en": {"engine.x": "X"}})
    second = Said({"hr": {"field.y": "Ipsilon"}, "en": {"field.y": "Why"}})
    app = FastAPI()
    app.include_router(plugins.router((first, second, object())), prefix="/api")
    _, body, sent = served("/api/words", None, app)
    assert sent[0]["status"] == 200
    assert json.loads(body) == {"hr": {"engine.x": "X", "field.y": "Ipsilon"},
                                "en": {"engine.x": "X", "field.y": "Why"}}


def test_a_word_said_in_one_language_only_or_twice_is_refused():
    with pytest.raises(plugins.PluginError, match="same keys"):
        plugins.words((Said({"hr": {"a": "A"}, "en": {}}),))
    twice = Said({"hr": {"a": "A"}, "en": {"a": "A"}})
    with pytest.raises(plugins.PluginError, match="two plugins"):
        plugins.words((twice, twice))
