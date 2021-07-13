import asyncio
import base64
import os
from http import HTTPStatus
from urllib.parse import ParseResult, urlparse, urlunparse

from .exceptions import BrokenHandshakeError, WsaioError
from .http import HTTPRequest, HTTPResponse
from .protocol import WebSocketProtocol, WebSocketProtocolState
from .websocket import WebSocketCloseCode, WebSocketFrame, WebSocketOpcode


class WebSocketClient:
    def __init__(self, loop=None):
        if loop is not None:
            self.loop = loop
        else:
            self.loop = asyncio.get_event_loop()

        self.protocol = None

        self._handshake_complete = self.loop.create_future()

    async def connection_made(self, transport):
        self.protocol.set_parser(HTTPResponse.parser(self.protocol))
        self.protocol.state = WebSocketProtocolState.HANDSHAKING

        result = ParseResult(
            '', '', self.url.path or '/', self.url.params, self.url.query, self.url.fragment
        )

        request = HTTPRequest(
            method='GET',
            path=urlunparse(result),
            headers=self.headers,
            body=b''
        )

        await self.protocol.write(request.serialize())

    def http_response_received(self, response):
        extra = {
            'response': response,
            'protocol': self
        }

        expected_status = HTTPStatus.SWITCHING_PROTOCOLS

        if response.status is not expected_status:
            self._handshake_complete.set_exception(
                BrokenHandshakeError(
                    f'Server responsed with status code {response.status} '
                    f'({response.phrase}), need status code {expected_status} '
                    f'({expected_status.phrase}) to complete handshake. '
                    f'Closing!',
                    extra
                )
            )
            return self.protocol.close()

        connection = response.headers.getone(b'connection')

        if connection is None or connection.lower() != b'upgrade':
            self._handshake_complete.set_exception(
                BrokenHandshakeError(
                    f'Server responded with "connection: {connection}", '
                    f'need "connection: upgrade" to complete handshake. '
                    f'Closing!',
                    extra
                )
            )
            return self.protocol.close()

        upgrade = response.headers.getone(b'upgrade')

        if upgrade is None or upgrade.lower() != b'websocket':
            self._handshake_complete.set_exception(
                BrokenHandshakeError(
                    f'Server responded with "upgrade: {upgrade}", '
                    f'need "upgrade: websocket" to complete handshake. '
                    f'Closing!',
                    extra
                )
            )
            return self.protocol.close()

        self.protocol.state = WebSocketProtocolState.IDLE
        self.protocol.set_parser(WebSocketFrame.parser(self.protocol))

        self._handshake_complete.set_result(None)

        self.protocol._run_callback('ws_connected')

    def data_received(self, data):
        pass

    def connection_lost(self, exc):
        pass

    def connection_closing(self, exc):
        pass

    async def parser_failed(self, exc):
        if exc is not None:
            if self.protocol.state is WebSocketProtocolState.HANDSHAKING:
                self._handshake_complete.set_exception(exc)
            else:
                close_code = WebSocketCloseCode.NORMAL_CLOSURE

                if isinstance(exc, WsaioError):
                    close_code = exc.get_extra('close_code', WebSocketCloseCode.NORMAL_CLOSURE)

                await self.send_close(close_code, str(exc).encode())

        self.protocol.close(exc)

    def ws_connected(self):
        pass

    def ws_frame_received(self, frame):
        pass

    def ws_binary_received(self, data):
        pass

    def ws_text_received(self, data):
        pass

    def ws_ping_received(self, data):
        pass

    def ws_pong_received(self, data):
        pass

    def ws_close_received(self, code, data):
        pass

    async def send_frame(self, frame, **kwargs):
        await self.protocol.write(frame.serialize(masked=True), **kwargs)

    def send_bytes(self, data, *, opcode=WebSocketOpcode.TEXT, **kwargs):
        return self.send_frame(WebSocketFrame(opcode=opcode, data=data), **kwargs)

    def send_str(self, data, *args, **kwargs):
        return self.send_bytes(data.encode(), *args, **kwargs)

    def send_ping(self, *args, **kwrags):
        return self.send_bytes(*args, **kwrags, opcode=WebSocketOpcode.PING)

    def send_pong(self, *args, **kwrags):
        return self.send_bytes(*args, **kwrags, opcode=WebSocketOpcode.PONG)

    async def send_close(self, code, data, *, drain=True):
        data = code.to_bytes(2, 'big', signed=False) + data
        await self.send_frame(
            WebSocketFrame(opcode=WebSocketOpcode.CLOSE, data=data, drain=drain)
        )

    async def connect(self, url, *args, **kwargs):
        self.sec_ws_key = base64.b64encode(os.urandom(16))

        self.headers = kwargs.pop('headers', {})

        self.url = urlparse(url)
        self.ssl = kwargs.pop('ssl', self.url.scheme == 'wss')
        self.port = kwargs.pop('port', 443 if self.ssl else 80)

        self.headers.update({
            'Host': f'{self.url.hostname}:{self.port}',
            'Connection': 'Upgrade',
            'Upgrade': 'websocket',
            'Sec-WebSocket-Key': self.sec_ws_key.decode(),
            'Sec-WebSocket-Version': 13
        })

        kwargs.setdefault('ssl', self.ssl)

        await self.loop.create_connection(
            lambda: WebSocketProtocol(self), self.url.hostname, self.port, *args, **kwargs
        )

        await self._handshake_complete
