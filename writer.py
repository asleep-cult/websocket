import asyncio
import socket
import ssl


class Writer:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        socket: socket.socket
    ):
        self.loop = loop
        self.socket = socket
        self.socket.setblocking(False)

    async def _wait_write(self):
        future = self.loop.create_future()

        def set_result():
            if not future.done():
                future.set_result(None)

        self.loop.add_writer(self.socket, set_result)
        await future

    async def write(self, *args, **kwargs):
        while True:
            try:
                return self.socket.send(*args, **kwargs)
            except (BlockingIOError, ssl.SSLWantWriteError):
                await self._wait_write()
