"""A file handed over that stops being read when nobody is taking it.

Starlette's FileResponse writes until the range ends and never listens for the
client leaving, and uvicorn quietly discards a send after a disconnect instead
of failing it. A player seeking asks for ``bytes=N-`` and drops the previous
connection each time, so every seek left a reader behind pulling the rest of
the file off the disk to its last byte: 78 of them at once on one spindle.
"""

import anyio
from starlette.responses import FileResponse as _FileResponse
from starlette.types import Message, Receive, Scope, Send


class _HungUp(Exception):
    pass


class FileResponse(_FileResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await super().__call__(scope, receive, send)
        gone = anyio.Event()

        # Refusing the next send rather than cancelling the reader: a cancel
        # lands inside the file's own close and leaves the descriptor open.
        async def sending(message: Message) -> None:
            if gone.is_set():
                raise _HungUp
            await send(message)

        async def watch() -> None:
            while (await receive())["type"] != "http.disconnect":
                pass
            gone.set()

        async with anyio.create_task_group() as group:
            group.start_soon(watch)
            try:
                await _FileResponse.__call__(self, scope, receive, sending)
            except _HungUp:
                pass
            group.cancel_scope.cancel()
