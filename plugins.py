"""Plugins: code an installation adds that no OPUS repository carries.

A plugin is a directory under ``/plugins`` whose ``opus-plugin.toml`` names, per
module, the object it hands that module::

    [modules]
    opus-library = "package.module:attribute"

The directory goes on the import path and the object is loaded; what it must
look like is the module's business, so the core only finds it. The image
installs each plugin's ``requirements/<module>.lock`` beside the module's own,
and the directory is mounted over what the image baked, so a plugin's code
reloads like the module's. An installation without one runs the same code with
nothing added.

A plugin that names a module and cannot be loaded stops the start: a module
that came up without what its installation added would be a silent loss of
exactly the thing somebody installed it for.

What a plugin says on screen comes with it, as ``words``: the same two
catalogues a module keeps, handed to the frontend at ``GET /words`` and laid
over the module's own, where saying a word again is the same error it is
between the kit and a module."""

import importlib
import os
import sys
import tomllib
from functools import cache
from pathlib import Path

from fastapi import APIRouter

ROOT = Path(os.environ.get("OPUS_PLUGIN_ROOT", "/plugins"))
MANIFEST = "opus-plugin.toml"
LOCALES = ("hr", "en")


class PluginError(Exception):
    pass


def directories(root: Path = ROOT) -> list[Path]:
    return sorted(manifest.parent for manifest in root.glob(f"*/{MANIFEST}"))


def load(module: str, root: Path = ROOT) -> tuple:
    """Every plugin's object for ``module``, in the order of their directories."""
    loaded = []
    for directory in directories(root):
        try:
            target = tomllib.loads((directory / MANIFEST).read_text())["modules"].get(module)
        except (OSError, tomllib.TOMLDecodeError, KeyError) as exc:
            raise PluginError(f"{directory.name}: unreadable {MANIFEST}: {exc}") from exc
        if target is None:
            continue
        if str(directory) not in sys.path:
            sys.path.append(str(directory))
        try:
            loaded.append(resolve(target))
        except PluginError as exc:
            raise PluginError(f"{directory.name}: {exc}") from exc
    return tuple(loaded)


@cache
def resolve(path: str):
    """The object at ``package.module:attribute``, or the module itself when no
    attribute is named. What a plugin hands over names its code this way, to be
    imported when first used rather than while the module that asks is still
    being put together."""
    name, _, attribute = path.partition(":")
    try:
        module = importlib.import_module(name)
        return getattr(module, attribute) if attribute else module
    except (ImportError, AttributeError) as exc:
        raise PluginError(f"{path} does not load: {exc}") from exc


def words(plugins: tuple) -> dict[str, dict[str, str]]:
    """The words of every plugin in one pair of catalogues. Both languages carry
    the same keys, and no two plugins say the same one."""
    merged: dict[str, dict[str, str]] = {locale: {} for locale in LOCALES}
    for plugin in plugins:
        said = getattr(plugin, "words", None) or {locale: {} for locale in LOCALES}
        if set(said) != set(LOCALES) or set(said["hr"]) != set(said["en"]):
            raise PluginError(f"{plugin!r}: words must carry the same keys in {', '.join(LOCALES)}")
        if again := set(said["hr"]) & set(merged["hr"]):
            raise PluginError(f"{', '.join(sorted(again))} is said by two plugins")
        for locale in LOCALES:
            merged[locale].update(said[locale])
    return merged


def router(plugins: tuple) -> APIRouter:
    """``GET /words``: what the installed plugins say, for the frontend to lay
    over the module's own catalogues."""
    said = words(plugins)
    routes = APIRouter()

    @routes.get("/words")
    async def plugin_words():
        return said

    return routes
