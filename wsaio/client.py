import base64
import os
import urllib.parse
from http import HTTPStatus

from .exceptions import BrokenHandshakeError
from .http import HttpRequest, HttpResponse, HttpResponseProtocol
from .protocol import BaseProtocol, BaseProtocolState
from .websocket import WebSocketFrame, WebSocketOpcode, WebSocketProtocol, \
    WebSocketState


class WebSocketClient(BaseProtocol, HttpResponseProtocol, WebSocketProtocol):
    def __init__(self, loop=None):
        BaseProtocol.__init__(self, loop)
        HttpResponseProtocol.__init__(self)
        WebSocketProtocol.__init__(self)
        self._handshake_complete = self.loop.create_future()

    def abort(self, exc=None):
        if exc is not None:
            if self.state is WebSocketState.HANDSHAKING:
                self._handshake_complete.set_exception(exc)
        super().abort(exc)

    def http_response_received(self, response: HttpResponse) -> None:
        extra = {
            'response': response,
            'protocol': self
        }

        expected_status = HTTPStatus.SWITCHING_PROTOCOLS
        if response.status != expected_status:
            return self.abort(
                BrokenHandshakeError(
                    f'Server responsed with status code {response.status} '
                    f'({response.phrase}), need status code {expected_status} '
                    f'({expected_status.phrase}) to complete handshake. '
                    'Aborting!',
                    extra
                )
            )

        connection = response.headers.getone(b'connection')
        if connection is None or connection.lower() != b'upgrade':
            return self.abort(
                BrokenHandshakeError(
                    f'Server responded with "connection: {connection}", '
                    f'need "connection: upgrade" to complete handshake. '
                    'Aborting!',
                    extra
                )
            )

        upgrade = response.headers.getone(b'upgrade')
        if upgrade is None or upgrade.lower() != b'websocket':
            return self.abort(
                BrokenHandshakeError(
                    f'Server responded with "upgrade: {upgrade}", '
                    f'need "upgrade: websocket" to complete handshake. '
                    'Aborting!',
                    extra
                )
            )

        self.state = BaseProtocolState.IDLE

        self.set_parser(WebSocketFrame.parser(self))
        self._handshake_complete.set_result(None)

        self.ws_connected()

    async def connect(self, url, *args, **kwargs):
        self.sec_ws_key = base64.b64encode(os.urandom(16))

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
            method='GET',
            path=url.path + url.params,
            headers=headers,
            body=b''
        )
        await self.write(request.encode(), drain=True)

        await self._handshake_complete

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
