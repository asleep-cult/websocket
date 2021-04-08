import base64
import os
import urllib.parse
from http import HTTPStatus

from .exceptions import BrokenHandshakeError, WsaioError
from .http import HttpRequest, HttpResponse, HttpResponseProtocol
from .protocol import BaseProtocol, BaseProtocolState, taskify
from .websocket import WebSocketCloseCode, WebSocketFrame, WebSocketOpcode, \
    WebSocketProtocol, WebSocketState


class WebSocketClient(BaseProtocol, HttpResponseProtocol, WebSocketProtocol):
    def __init__(self, loop=None):
        BaseProtocol.__init__(self, loop)
        HttpResponseProtocol.__init__(self)
        WebSocketProtocol.__init__(self)
        self._handshake_complete = self.loop.create_future()

    strstate = WebSocketProtocol.strstate

    def http_response_received(self, response: HttpResponse) -> None:
        extra = {
            'response': response,
            'protocol': self
        }

        expected_status = HTTPStatus.SWITCHING_PROTOCOLS
        if response.status != expected_status:
            return self._close(
                BrokenHandshakeError(
                    f'Server responsed with status code {response.status} '
                    f'({response.phrase}), need status code {expected_status} '
                    f'({expected_status.phrase}) to complete handshake. '
                    'Closing!',
                    extra
                )
            )

        connection = response.headers.getone(b'connection')
        if connection is None or connection.lower() != b'upgrade':
            return self._close(
                BrokenHandshakeError(
                    f'Server responded with "connection: {connection}", '
                    f'need "connection: upgrade" to complete handshake. '
                    'Closing!',
                    extra
                )
            )

        upgrade = response.headers.getone(b'upgrade')
        if upgrade is None or upgrade.lower() != b'websocket':
            return self._close(
                BrokenHandshakeError(
                    f'Server responded with "upgrade: {upgrade}", '
                    f'need "upgrade: websocket" to complete handshake. '
                    'Closing!',
                    extra
                )
            )

        self.state = BaseProtocolState.IDLE

        self.set_parser(WebSocketFrame.parser(self))
        self._handshake_complete.set_result(None)

        self.ws_connected()

    @taskify
    async def connection_made(self, transport):
        super().connection_made(transport)
        request = HttpRequest(
            method='GET',
            path=self.url.path + self.url.params,
            headers=self.headers,
            body=b''
        )
        await self.write(request.encode())

    async def connect(self, url, *args, **kwargs):
        self.sec_ws_key = base64.b64encode(os.urandom(16))

        self.headers = kwargs.pop('headers', {})

        self.set_parser(HttpResponse.parser(self))

        self.url = urllib.parse.urlparse(url)
        self.ssl = kwargs.pop('ssl', self.url.scheme == 'wss')
        self.port = kwargs.pop('port', 443 if self.ssl else 80)

        self.headers.update({
            'Host': f'{self.url.hostname}:{self.port}',
            'Connection': 'Upgrade',
            'Upgrade': 'websocket',
            'Sec-WebSocket-Key': self.sec_ws_key.decode(),
            'Sec-WebSocket-Version': 13
        })

        self.state = WebSocketState.HANDSHAKING

        await self.loop.create_connection(
            lambda: self, self.url.hostname,
            self.port, *args, ssl=self.ssl, **kwargs
        )

        await self._handshake_complete

    def parser_invalid_data(self, exc):
        self._close(exc)

    @taskify
    async def _close(self, exc=None):
        if exc is not None:
            if self.state is WebSocketState.HANDSHAKING:
                self._handshake_complete.set_exception(exc)
            else:
                close_code = WebSocketCloseCode.NORMAL_CLOSURE
                if isinstance(exc, WsaioError):
                    close_code = exc.get_extra(
                        'close_code',
                        WebSocketCloseCode.NORMAL_CLOSURE
                    )
                await self._send_close(close_code, str(exc).encode())
        super()._close(exc)

    async def _send_close(
        self,
        code: int,
        data: bytes,
        *,
        drain: bool = True
    ) -> None:
        code = code.to_bytes(2, 'big', signed=False)
        await self.send_frame(
            WebSocketFrame(
                opcode=WebSocketOpcode.CLOSE,
                data=code + (data or b'')
            ),
            drain=drain
        )

    async def close(
        self,
        code: int,
        data: bytes = None,
        *,
        drain: bool = True
    ) -> None:
        await self._send_close(code, data, drain=drain)
        super()._close()

    async def send_frame(
        self,
        frame: WebSocketFrame,
        *,
        drain: bool = False
    ) -> None:
        await self.write(frame.encode(masked=True), drain=drain)

    async def send_bytes(
        self,
        data: bytes,
        *,
        opcode: WebSocketOpcode = WebSocketOpcode.TEXT,
        drain: bool = False
    ) -> None:
        await self.send_frame(
            WebSocketFrame(
                opcode=opcode,
                data=data
            ),
            drain=drain
        )

    async def send_str(
        self,
        data: str,
        *,
        opcode: WebSocketOpcode = WebSocketOpcode.TEXT,
        drain: bool = False
    ) -> None:
        await self.send_bytes(data.encode(), opcode=opcode, drain=drain)
