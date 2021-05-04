import asyncio
import enum
import functools

from .exceptions import ConnectionClosedError, ParserInvalidDataError


class BaseProtocolState(enum.IntEnum):
    INIT = 0
    IDLE = 1
    CLOSED = 3
    PARSING = 2


class BaseProtocol(asyncio.Protocol):
    # Stolen from asyncio.streams.FlowControlMixin
    def __init__(self, loop=None):
        if loop is None:
            self.loop = asyncio.get_event_loop()
        else:
            self.loop = loop
        self._paused = False
        self._drain_waiter = None
        self._connection_lost = False
        self._parser = None
        self.transport = None
        self.state = BaseProtocolState.INIT

    def strstate(self):
        if self.state is BaseProtocolState.INIT:
            return 'initialized'
        elif self.state is BaseProtocolState.IDLE:
            return 'idling'
        elif self.state is BaseProtocolState.PARSING:
            return 'parsing'
        elif self.state is BaseProtocolState.CLOSED:
            return 'closed'

    def _close(self, exc=None):
        self.closing_connection(exc)
        self.state = BaseProtocolState.CLOSED
        self.transport.close()

    def connection_made(self, transport):
        self.transport = transport

    def set_parser(self, parser):
        parser.send(None)
        self._parser = parser

    def data_received(self, data):
        state = self.state
        self.state = BaseProtocolState.PARSING
        while data:
            try:
                self._parser.send(data)
                self.state = state
                return
            except StopIteration as e:
                # the parser must have changed, e.value is the unused data
                data = e.value
            except ParserInvalidDataError as e:
                self._close(e)
                return
        self.state = state

    def pause_writing(self):
        assert not self._paused
        self._paused = True

    def resume_writing(self):
        assert self._paused
        self._paused = False

        waiter = self._drain_waiter
        if waiter is not None:
            self._drain_waiter = None
            if not waiter.done():
                waiter.set_result(None)

    def connection_lost(self, exc):
        self._connection_lost = True
        # Wake up the writer if currently paused.
        if not self._paused:
            return
        waiter = self._drain_waiter
        if waiter is None:
            return
        self._drain_waiter = None
        if waiter.done():
            return
        if exc is None:
            waiter.set_result(None)
        else:
            waiter.set_exception(exc)

    async def drain(self):
        if self._connection_lost:
            raise ConnectionResetError('Connection lost')
        if not self._paused:
            return
        waiter = self._drain_waiter
        assert waiter is None or waiter.cancelled()
        waiter = self.loop.create_future()
        self._drain_waiter = waiter
        await waiter

    async def write(self, data: bytes, *, drain: bool = False) -> None:
        extra = {
            'protocol': self,
            'data': data
        }
        if self.state is BaseProtocolState.CLOSED:
            raise ConnectionClosedError(
                'Attempt to write to a closed/closing transport',
                extra)

        self.transport.write(data)
        if drain:
            await self.drain()

    def closing_connection(self, exc) -> None:
        pass


def taskify(func):
    @functools.wraps(func)
    def callback(protocol, *args, **kwargs):
        protocol.loop.create_task(func(protocol, *args, **kwargs))
    return callback
