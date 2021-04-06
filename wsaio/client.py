import asyncio
import base64
import os
import urllib.parse
from http import HTTPStatus

from .exceptions import UnexpectedHttpResponse
from .http import HttpProtocol, HttpRequest, HttpResponse
from .websocket import WebSocketFrame, WebSocketProtocol


class WebSocketClient(asyncio.Protocol, HttpProtocol, WebSocketProtocol):
    def __init__(self, loop=None):
        self.loop = loop or asyncio.get_event_loop()
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
            if e.value:
                self._parser.send(e.value)

    def http_response_received(self, response: HttpResponse):
        if response.status != HTTPStatus.SWITCHING_PROTOCOLS:
            self._have_headers.set_exception(
                UnexpectedHttpResponse(
                    f'Expected status code {HTTPStatus.SWITCHING_PROTOCOLS}, '
                    f'got {response.status}',
                    response
                )
            )

        connection = response._get_lower(b'connection', response.headers)
        if connection is not None and connection.lower() != b'upgrade':
            self._have_headers.set_exception(
                UnexpectedHttpResponse(
                    f'Expected "connection: upgrade" header, got {connection}',
                    response
                )
            )

        upgrade = response._get_lower(b'upgrade', response.headers)
        if upgrade is not None and upgrade.lower() != b'websocket':
            self._have_headers.set_exception(
                UnexpectedHttpResponse(
                    f'Expected "upgrade: websocket" header, got {upgrade}',
                    response
                )
            )

        self.set_parser(WebSocketFrame.parser(self))
        self._have_headers.set_result(None)

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
            'Host': '{}:{}'.format(url.hostname, port),
            'Connection': 'Upgrade',
            'Upgrade': 'websocket',
            'Sec-WebSocket-Key': self.sec_ws_key.decode(),
            'Sec-WebSocket-Version': 13
        })

        request = HttpRequest(
            method='GET', path=url.path + url.params, headers=headers
        )
        self.transport.write(request.encode())

        await self._have_headers
