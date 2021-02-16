import asyncio
import socket


class Reader:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        socket: socket.socket
    ) -> None:
        self.loop = loop
        self.buffer = bytearray()
        self.buffer_index = 0
        self.socket = socket
        self.socket.setblocking(False)

    async def _wait_read(self) -> None:
        future = self.loop.create_future()
        self.loop.add_reader(self.socket, future.set_result, None)
        await future

    def _read_from_buf(self, bufsize) -> memoryview:
        view = memoryview(self.buffer)
        buffer = view[self.buffer_index:self.buffer_index + bufsize]
        self.buffer_index += len(buffer)

        if self.buffer_index >= len(self.buffer):
            self.buffer_index = 0
            self.buffer = bytearray()

        return buffer

    async def _read_into_buf(self):
        while True:
            try:
                return self.buffer.extend(self.socket.recv(1024))
            except BlockingIOError:
                await self._wait_read()

    async def read(self, bufsize) -> memoryview:
        if not self.buffer:
            await self._read_into_buf()

        return self._read_from_buf(bufsize)

    async def read_all(self, bufsize) -> memoryview:
        while True:
            if len(self.buffer) - self.buffer_index >= bufsize:
                return self._read_from_buf(bufsize)

            await self._read_into_buf()

    async def read_until(self, string) -> memoryview:
        sub = string.encode()

        while True:
            try:
                index = self.buffer.index(sub, self.buffer_index)
            except ValueError:
                await self._read_into_buf()

            return self._read_into_buf(index)
