"""What a module's tests stand a store on when they have no database."""

import asyncio
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select


class Table:
    """A sessionmaker over one dict of settings. A read may be held at `gate`
    to see what a write does meanwhile."""

    def __init__(self, rows: dict[str, str] | None = None):
        self.rows = dict(rows or {})
        self.gate: asyncio.Event | None = None
        self.commits = 0

    def __call__(self):
        return _Session(self)


class _Session:
    def __init__(self, table: Table):
        self.table = table
        self.written: dict[str, str] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):
        if isinstance(statement, Select):
            seen = dict(self.table.rows)
            if self.table.gate is not None:
                await self.table.gate.wait()
            rows = [SimpleNamespace(key=key, value=value) for key, value in seen.items()]
            return SimpleNamespace(scalars=lambda: rows)
        params = statement.compile(dialect=postgresql.dialect()).params
        self.written[params["key"]] = params["value"]

    async def commit(self):
        self.table.rows.update(self.written)
        self.table.commits += 1
