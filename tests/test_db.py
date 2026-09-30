import asyncio
import contextlib

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from opus_core.db import connect, session_dependency


def test_one_engine_behind_the_sessions_and_the_route_session_closes():
    async def scenario():
        engine, sessions = connect("postgresql+psycopg://nobody@nowhere/none")
        assert sessions.kw["bind"] is engine and engine.pool._pre_ping
        route = session_dependency(sessions)()
        session = await anext(route)
        assert isinstance(session, AsyncSession)
        await route.aclose()
        await engine.dispose()

    asyncio.run(scenario())


def test_every_connection_asks_the_database_not_to_compile_statements():
    asked = {}

    async def scenario():
        engine, _ = connect("postgresql+psycopg://nobody@nowhere/none")

        @event.listens_for(engine.sync_engine, "do_connect")
        def connecting(dialect, record, cargs, cparams):
            asked.update(cparams)
            raise ConnectionRefusedError

        with contextlib.suppress(Exception):
            await engine.connect()
        await engine.dispose()

    asyncio.run(scenario())
    assert asked["options"] == "-c jit=off"
