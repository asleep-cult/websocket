import asyncio
import socket


class Reader:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        socket: socket.socket
    ) -> None:
        self.loop = loop
        self.socket = socket
        self.socket.setblocking(False)

    async def _wait_read(self):
        future = self.loop.create_future()
        self.loop.add_reader(self.socket, future.set_result, None)
        await future

    async def read_into(self, *args, **kwargs) -> int:
        while True:
            try:
                return self.socket.recv_into(*args, **kwargs)
            except BlockingIOError:
                await self._wait_read()

    async def read(self, *args, **kwargs) -> bytes:
        while True:
            try:
                return self.socket.recv(*args, **kwargs)
            except BlockingIOError:
                await self._wait_read()

    async def read_all(self, bufsize) -> bytearray:
        buffer = bytearray(bufsize)
        while True:
            await self.read_into(buffer)
            if len(buffer) == bufsize:
                return buffer
