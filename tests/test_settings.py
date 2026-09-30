import asyncio
from dataclasses import dataclass

import pytest
from sqlalchemy import String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from opus_core.settings import RuntimeConfig, SettingSpec, SettingsValidationError, Store
from opus_core.testing import Table


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Config(RuntimeConfig):
    spec = (
        SettingSpec("url", "engine", "http://default"),
        SettingSpec("password", "engine", "", secret=True),
        SettingSpec("enabled", "engine", "false", kind="bool"),
        SettingSpec("order", "engine", "a", kind="select", options=("a", "b")),
        SettingSpec("workers", "engine", "4", kind="number"),
        SettingSpec("box", "engine", "", kind="number"),
        SettingSpec("engine_port", "engine", "80", label="port"),
        SettingSpec("learned", "engine", "", secret=True, hidden=True),
        SettingSpec("access_token", "access", "", secret=True),
    )


def _https_only(spec: SettingSpec, value: str) -> None:
    if spec.key == "url" and not value.startswith("https://"):
        raise SettingsValidationError(spec.key, "bad_url")


def store(rows: dict[str, str] | None = None) -> tuple[Store, Table]:
    table = Table(rows)
    return Store(Config, Setting, table, _https_only), table


def refused(coroutine) -> tuple[str, str]:
    with pytest.raises(SettingsValidationError) as error:
        asyncio.run(coroutine)
    return error.value.key, error.value.code


def test_a_key_not_in_the_table_reads_as_its_default():
    settings, _ = store({"url": "https://there"})
    config = asyncio.run(settings.runtime())
    assert (config.get("url"), config.get("workers"), config.float("workers")) == (
        "https://there", "4", 4.0)
    assert not config.bool("enabled")


def test_a_config_built_by_hand_falls_back_to_the_spec():
    assert Config({}).get("order") == "a"
    with pytest.raises(KeyError):
        Config({}).get("no_such_key")


@pytest.mark.parametrize(("key", "value", "code"), [
    ("nope", "1", "unknown_key"),
    ("learned", "x", "not_editable"),
    ("access_token", "x", "not_editable"),
    ("enabled", "yes", "bad_value"),
    ("order", "c", "bad_value"),
    ("workers", "many", "not_a_number"),
    ("workers", "", "not_a_number"),
    ("url", "http://plain", "bad_url"),
])
def test_what_the_form_may_not_write_is_refused(key, value, code):
    settings, table = store()
    assert refused(settings.update({key: value})) == (key, code)
    assert table.rows == {} and table.commits == 0


def test_a_bad_value_after_a_good_one_writes_neither():
    settings, table = store()
    assert refused(settings.update({"order": "b", "enabled": "maybe"})) == ("enabled", "bad_value")
    assert table.rows == {}


def test_a_number_without_a_default_may_be_left_unset():
    settings, table = store({"box": "3"})
    assert asyncio.run(settings.update({"box": ""})) == {"box": "3"}
    assert table.rows["box"] == ""


def test_a_blank_secret_leaves_what_is_stored():
    settings, table = store({"password": "kept"})
    asyncio.run(settings.update({"password": "", "order": "b"}))
    assert table.rows == {"password": "kept", "order": "b"}


def test_an_update_says_what_each_changed_key_held():
    settings, _ = store({"order": "b"})
    changed = asyncio.run(settings.update({"order": "b", "url": "https://new", "enabled": "true"}))
    assert changed == {"url": "http://default", "enabled": "false"}


def test_nothing_to_write_touches_nothing():
    settings, table = store({"password": "kept"})
    assert asyncio.run(settings.update({"password": ""})) == {}
    assert table.commits == 0


def test_credentials_are_written_blank_or_not_but_only_known_keys():
    settings, table = store({"learned": "old"})
    asyncio.run(settings.store_credentials({"learned": "", "access_token": "minted"}))
    assert table.rows == {"learned": "", "access_token": "minted"}
    assert refused(settings.store_credentials({"nope": "x"})) == ("nope", "unknown_key")


def test_the_form_sees_no_secret_and_nothing_hidden():
    settings, _ = store({"password": "p", "learned": "l", "engine_port": "81"})
    shown = {s["key"]: s for s in asyncio.run(settings.for_ui())}
    assert "learned" not in shown
    assert shown["password"]["value"] == "" and shown["password"]["is_set"] is True
    assert shown["engine_port"] == {
        "key": "engine_port", "group": "engine", "secret": False, "kind": "text",
        "options": [], "label": "port", "value": "81", "is_set": None}
    assert shown["order"]["options"] == ["a", "b"] and shown["order"]["label"] == "order"


def test_a_module_field_is_shown_with_the_rest():
    @dataclass(frozen=True)
    class Scoped(SettingSpec):
        scope: str = "both"

    class Scoping(RuntimeConfig):
        spec = (Scoped("url", "engine", "", scope="external"),)

    settings = Store(Scoping, Setting, Table())
    assert asyncio.run(settings.for_ui())[0]["scope"] == "external"


def test_a_read_is_held_until_a_write():
    settings, table = store({"order": "a"})

    async def scenario():
        first = await settings.runtime()
        table.rows["order"] = "b"
        held = await settings.runtime()
        await settings.update({"enabled": "true"})
        return first, held, await settings.runtime()

    first, held, after = asyncio.run(scenario())
    assert held is first
    assert (after.get("order"), after.get("enabled")) == ("b", "true")


def test_a_read_that_began_before_a_write_is_not_kept():
    settings, table = store({"url": "https://old"})

    async def scenario():
        table.gate = asyncio.Event()
        reading = asyncio.create_task(settings.runtime())
        await asyncio.sleep(0)
        gate, table.gate = table.gate, None
        await settings.update({"url": "https://new"})
        gate.set()
        stale = await reading
        return stale.get("url"), settings._held, (await settings.runtime()).get("url")

    assert asyncio.run(scenario()) == ("https://old", None, "https://new")
