"""Runtime configuration a person edits on the Settings page, kept in one
key/value table. Which keys a module has and what each of them accepts is the
module's; how they are read, held, shown and written is the same everywhere
and lives here."""

from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

# written by the module itself — a generated token, a password somebody chose
# on its own screen — and never through the settings form
ACCESS = "access"


class SettingsValidationError(Exception):
    def __init__(self, key: str, code: str):
        super().__init__(f"{key}: {code}")
        self.key = key
        self.code = code


@dataclass(frozen=True)
class SettingSpec:
    key: str
    group: str
    default: str
    secret: bool = False
    kind: str = "text"  # text | bool | select | number | list
    options: tuple[str, ...] = ()
    # what the shared field control looks its label up by: the key itself,
    # unless one label serves many keys
    label: str = ""
    # a machine credential the module generates or learns: stored and
    # validated like any setting, never shown, never typed
    hidden: bool = False

    def __post_init__(self):
        if not self.label:
            object.__setattr__(self, "label", self.key)


def check_kind(spec: SettingSpec, value: str) -> None:
    if spec.kind == "bool":
        if value not in ("true", "false"):
            raise SettingsValidationError(spec.key, "bad_value")
    elif spec.kind == "select":
        if value not in spec.options:
            raise SettingsValidationError(spec.key, "bad_value")
    elif spec.kind == "number":
        # a number without a default may be left unset
        if value == "" and spec.default == "":
            return
        try:
            float(value)
        except ValueError:
            raise SettingsValidationError(spec.key, "not_a_number")


@dataclass(frozen=True)
class RuntimeConfig:
    """The settings as one read saw them. A module subclasses it with its
    `spec`, which is where a key not in the table takes its default from."""

    spec: ClassVar[tuple[SettingSpec, ...]] = ()
    by_key: ClassVar[dict[str, SettingSpec]] = {}

    values: dict[str, str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.by_key = {s.key: s for s in cls.spec}

    def get(self, key: str) -> str:
        return self.values.get(key, self.by_key[key].default)

    def bool(self, key: str) -> bool:
        return self.get(key).strip().lower() in ("1", "true", "yes", "on")

    def float(self, key: str) -> float:
        try:
            return float(self.get(key))
        except ValueError:
            return float(self.by_key[key].default)


def _no_rule(spec: SettingSpec, value: str) -> None:
    pass


class Store:
    """One module's settings table.

    Every read and write opens a session of its own that ends before the caller
    goes on: a route that then spends a minute on a search or a stream must not
    hold a pooled connection idle for all of it.

    What was read is held, because it is asked for on every request — by the
    guard and then again by the route — and a thumbnail or a proxied asset is a
    request. That is safe because there is one process and every write goes
    through this store, which drops it; a row changed by hand in psql is seen
    after a restart. A read that began before a write is answered but not kept:
    what it read may be the value the write replaced."""

    def __init__(self, config: type[RuntimeConfig], model: Any,
                 sessions: async_sessionmaker,
                 validate: Callable[[SettingSpec, str], None] = _no_rule):
        self.config = config
        self._model = model
        self.sessions = sessions
        self._validate = validate
        self._held: RuntimeConfig | None = None
        self._generation = 0

    def forget(self) -> None:
        self._held = None
        self._generation += 1

    async def _stored(self) -> dict[str, str]:
        async with self.sessions() as session:
            result = await session.execute(select(self._model))
            return {row.key: row.value for row in result.scalars()}

    async def _write(self, values: dict[str, str]) -> None:
        async with self.sessions() as session:
            for key, value in values.items():
                await session.execute(
                    insert(self._model)
                    .values(key=key, value=value)
                    .on_conflict_do_update(index_elements=["key"], set_={"value": value})
                )
            await session.commit()
        self.forget()

    async def runtime(self) -> RuntimeConfig:
        if self._held is not None:
            return self._held
        began = self._generation
        stored = await self._stored()
        read = self.config({spec.key: stored.get(spec.key, spec.default)
                            for spec in self.config.spec})
        if began == self._generation:
            self._held = read
        return read

    async def for_ui(self) -> list[dict]:
        stored = await self._stored()
        out = []
        for spec in self.config.spec:
            if spec.hidden:
                continue
            value = stored.get(spec.key, spec.default)
            shown = {f.name: getattr(spec, f.name) for f in fields(spec)
                     if f.name not in ("default", "hidden")}
            shown["options"] = list(spec.options)
            # never echo a stored secret back; report only whether it is set
            shown["value"] = "" if spec.secret else value
            shown["is_set"] = bool(value) if spec.secret else None
            out.append(shown)
        return out

    async def update(self, updates: dict[str, str]) -> dict[str, str]:
        """Write what a person changed on the form, and return what each
        changed key held before — the difference a running service may have
        to be told. Every key is checked before anything is written."""
        writes: dict[str, str] = {}
        for key, value in updates.items():
            spec = self.config.by_key.get(key)
            if spec is None:
                raise SettingsValidationError(key, "unknown_key")
            if spec.hidden or spec.group == ACCESS:
                raise SettingsValidationError(key, "not_editable")
            # a blank submission for a secret means "leave unchanged"
            if spec.secret and value == "":
                continue
            check_kind(spec, value)
            self._validate(spec, value)
            writes[key] = value
        if not writes:
            return {}
        stored = await self._stored()
        before = {key: stored.get(key, self.config.by_key[key].default) for key in writes}
        await self._write(writes)
        return {key: old for key, old in before.items() if writes[key] != old}

    async def store_credentials(self, values: dict[str, str]) -> None:
        """Write values the module itself produced — a generated token, a
        rotated OAuth token, a password somebody just chose.

        Deliberately not `update`: that one serves a form, where a blank secret
        means "leave it alone" and every value is checked against what a person
        might mistype. Neither applies here, and the first rule would make
        clearing a credential impossible."""
        for key in values:
            if key not in self.config.by_key:
                raise SettingsValidationError(key, "unknown_key")
        await self._write(values)
