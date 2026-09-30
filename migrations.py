"""The body of every module's alembic env.py: the module hands in its database
and its models, and alembic runs over them online or writes the SQL offline."""

import asyncio

from alembic import context
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine


def _migrate(connection, metadata: MetaData):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _online(url: str, metadata: MetaData):
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(_migrate, metadata)
    await engine.dispose()


def run(url: str, metadata: MetaData) -> None:
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        asyncio.run(_online(url, metadata))
