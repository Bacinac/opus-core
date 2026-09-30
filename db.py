from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def connect(url: str) -> tuple[AsyncEngine, async_sessionmaker]:
    # PostgreSQL compiles a statement whose cost the planner guesses high; on
    # tables this size the guess is wrong often enough to cost 200 ms of
    # compiling for a photograph query that runs in 30
    engine = create_async_engine(url, pool_pre_ping=True, connect_args={"options": "-c jit=off"})
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def session_dependency(sessions: async_sessionmaker):
    """A route's session, closed when the response is done."""
    async def get_session():
        async with sessions() as session:
            yield session
    return get_session
