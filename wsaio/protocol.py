import asyncio
import enum

from .exceptions import ConnectionClosedError, ParserInvalidDataError


class WebSocketProtocolState(enum.IntEnum):
    INIT = 0
    IDLE = 1
    PARSING = 2
    CLOSED = 3
    HANDSHAKING = 4


class WebSocketProtocol(asyncio.BaseProtocol):
    def __init__(self, client):
        self.client = client
        self.client.protocol = self
        self.loop = self.client.loop

        self._paused = False
        self._drain_waiter = None

        self._parser = None

        self.transport = None
        self.state = WebSocketProtocolState.INIT

        self.extensions = []

    def _run_callback(self, name, *args, **kwargs):
        func = getattr(self.client, name)
        coro = func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            self.loop.create_task(coro)

    def _set_paused(self, paused):
        assert self._paused is (not paused)
        self._paused = paused

    def connection_made(self, transport):
        self.transport = transport
        self._run_callback('connection_made', transport)

    def set_parser(self, parser):
        parser.send(None)
        self._parser = parser

    def data_received(self, data):
        state = self.state

        self.state = WebSocketProtocolState.PARSING

        while data:
            try:
                self._parser.send(data)
                break
            except StopIteration as err:
                data = err.value
            except ParserInvalidDataError as err:
                self._run_callback('parser_invalid_data', err)
                break

        self.state = state

        self._run_callback('data_received', data)

    def pause_writing(self):
        self._set_paused(True)

    def resume_writing(self):
        self._set_paused(False)

        waiter = self._drain_waiter

        if waiter is not None:
            self._drain_waiter = None

            if not waiter.done():
                waiter.set_result(None)

    def connection_lost(self, exc):
        self.state = WebSocketProtocolState.CLOSED

        if not self._paused:
            return

        waiter = self._drain_waiter

        if waiter is None:
            return

        self._drain_waiter = None

        if waiter.done():
            return

        if exc is not None:
            waiter.set_result(exc)
        else:
            waiter.set_result(None)

        self._run_callback('connection_lost', exc)

    def connection_closing(self, exc):
        self._run_callback('connection_closing', exc)

    def http_response_received(self, response):
        self._run_callback('http_response_received', response)

    def ws_connected(self):
        self._run_callback('ws_connected')

    def ws_frame_received(self, frame):
        self._run_callback('ws_frame_received', frame)

    def ws_binary_received(self, data):
        self._run_callback('ws_binary_received', data)

    def ws_text_received(self, data):
        self._run_callback('ws_text_received', data)

    def ws_ping_received(self, data):
        self._run_callback('ws_ping_received', data)

    def ws_pong_received(self, data):
        self._run_callback('ws_pong_received', data)

    def ws_close_received(self, code, data):
        self._run_callback('ws_close_received', data)

    async def drain(self):
        if self.state is WebSocketProtocolState.CLOSED:
            raise ConnectionClosedError(
                'Attempt to drain a closed transport', {'protocol': self}
            )

        if not self._paused:
            return

        assert self._drain_waiter is None or self._drain_waiter.cancelled()

        waiter = self._drain_waiter = self.loop.create_future()

        return waiter

    async def write(self, data, *, wait=False):
        if self.state is WebSocketProtocolState.CLOSED:
            raise ConnectionClosedError(
                'Attempt to write to a closed transport', {'procotol': self}
            )

        self.transport.write(data)

        if wait:
            await self.drain()

    def close(self, exc=None):
        self.state = WebSocketProtocolState.CLOSED
        self._run_callback('connection_closing', exc)

        if self.transport is not None:
            self.transport.close()
