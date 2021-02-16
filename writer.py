import asyncio
import socket


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
        self.loop.add_writer(self.socket, future.set_result, None)
        await future

    async def write(self, *args, **kwargs):
        while True:
            try:
                return self.socket.send(*args, **kwargs)
            except BlockingIOError:
                await self._wait_write()
