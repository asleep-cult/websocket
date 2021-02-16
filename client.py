import socket
import asyncio
import functools
import urllib
import os
from base64 import b64encode
from frame import Frame, Opcode
from reader import Reader
from writer import Writer
from typing import Optional, Tuple, Dict, Any


class Client:
    def __init__(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        sock: Optional[socket.socket] = None
    ) -> None:
        self.loop = loop or asyncio.get_event_loop()

        if sock is not None:
            self.socket = sock
        else:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.reader = Reader(self.loop, self.socket)
        self.writer = Writer(self.loop, self.socket)

        self.url = None
        self.ws_key = None
        self.ws_versions = None

    async def connect(
        self, url, port: Optional[int] = None,
        ws_versions: Tuple[str] = ('13',),
        headers: Optional[Dict[str, Any]] = None
    ):
        self.url = urllib.parse.urlparse(url)
        self.ws_versions = ws_versions

        if port is not None:
            self.url.port = port

        await self.loop.run_in_executor(
            None, functools.partial(
                self.socket.connect, (self.url.hostname, self.url.port)
            )
        )

        await self._send_initial_request(headers or {})

    async def _send_initial_request(self, headers):
        self.ws_key = b64encode(os.urandom(16)).decode()
        hdrs = {
            'Host': self.url.hostname,
            'Connection': 'upgrade',
            'Upgrade': 'WebSocket',
            'Sec-WebSocket-Key': self.ws_key,
            'Sec-WebSocket-Version': ', '.join(self.ws_versions),
            **headers
        }

        hdrs = '\r\n'.join(('%s: %s;' % (k, v)) for k, v in hdrs.items())
        request = 'GET %s HTTP/1.1\r\n%s\r\n\r\n' % (self.url.path, hdrs)

        await self.writer.write(request.encode())

    async def send_frame(self, frame: Frame) -> None:
        await self.writer.write(frame.encode())

    async def receive_frame(self) -> Frame:
        frame = await Frame.create(self.reader)
        return frame

    async def receive_text_encoded(self) -> bytearray:
        frame = await self.receive_frame()
        if frame.opcode == Opcode.TEXT:
            return frame.data
        else:
            raise ValueError(
                'Received Opcode {}, not TEXT'.format(frame.opcode)
            )

    async def receive_text(self):
        return (await self.receive_text_encoded()).decode()

    async def receive_binary(self) -> bytearray:
        frame = await self.receive_frame()
        if frame.opcode == Opcode.BINARY:
            return frame.data
        else:
            raise ValueError(
                'Received Opcode {}, not BINARY'.format(frame.opcode)
            )
