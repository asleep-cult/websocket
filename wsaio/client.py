import base64
import os
import urllib.parse
from http import HTTPStatus

from .exceptions import UnexpectedHttpResponse
from .http import HttpProtocol, HttpRequest, HttpResponse
from .protocol import DrainableProtocol
from .websocket import WebSocketFrame, WebSocketOpcode, WebSocketProtocol


class WebSocketClient(DrainableProtocol, HttpProtocol, WebSocketProtocol):
    def __init__(self, loop=None):
        super().__init__(loop)
        self.transport = None
        self._have_headers = self.loop.create_future()
        self._parser = None
        self.sec_ws_key = base64.b64encode(os.urandom(16))

    def set_parser(self, parser):
        parser.send(None)
        self._parser = parser

    def data_received(self, data):
        try:
            self._parser.send(data)
        except StopIteration as e:
            # the parser must have changed, e.value is the unused data
            if e.value:
                self._parser.send(e.value)

    def http_response_received(self, response: HttpResponse) -> None:
        if response.status != HTTPStatus.SWITCHING_PROTOCOLS:
            return self._have_headers.set_exception(
                UnexpectedHttpResponse(
                    f'Expected status code {HTTPStatus.SWITCHING_PROTOCOLS}, '
                    f'got {response.status}',
                    response
                )
            )

        connection = response.headers.getone(b'connection')
        if connection is None or connection.lower() != b'upgrade':
            return self._have_headers.set_exception(
                UnexpectedHttpResponse(
                    f'Expected "connection: upgrade" header, got {connection}',
                    response
                )
            )

        upgrade = response.headers.getone(b'upgrade')
        if upgrade is None or upgrade.lower() != b'websocket':
            return self._have_headers.set_exception(
                UnexpectedHttpResponse(
                    f'Expected "upgrade: websocket" header, got {upgrade}',
                    response
                )
            )

        self.set_parser(WebSocketFrame.parser(self))
        self._have_headers.set_result(None)
        self.ws_connected()

    async def connect(self, url, *args, **kwargs):
        headers = kwargs.pop('headers', {})

        self.set_parser(HttpResponse.parser(self))

        url = urllib.parse.urlparse(url)
        ssl = kwargs.pop('ssl', url.scheme == 'wss')
        port = kwargs.pop('port', 443 if ssl else 80)

        self.transport, _ = await self.loop.create_connection(
            lambda: self, url.hostname, port, *args, ssl=ssl, **kwargs
        )

        headers.update({
            'Host': f'{url.hostname}:{port}',
            'Connection': 'Upgrade',
            'Upgrade': 'websocket',
            'Sec-WebSocket-Key': self.sec_ws_key.decode(),
            'Sec-WebSocket-Version': 13
        })

        request = HttpRequest(
            method='GET', path=url.path + url.params, headers=headers
        )
        await self.write(request.encode(), drain=True)

        await self._have_headers

    async def write(self, data: bytes, *, drain: bool = False) -> None:
        self.transport.write(data)
        if drain:
            await self.drain()

    async def send_frame(
        self, frame: WebSocketFrame, *, drain: bool = False
    ) -> None:
        await self.write(frame.encode(masked=True), drain=drain)

    async def send_bytes(self, data: bytes, *, drain: bool = False) -> None:
        await self.send_frame(
            WebSocketFrame(opcode=WebSocketOpcode.TEXT, data=data),
            drain=drain
        )

    async def send_str(self, data: str, *, drain: bool = False) -> None:
        await self.send_bytes(data.encode(), drain=drain)
