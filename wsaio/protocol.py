import asyncio
import functools


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
        except Exception as e:
            self.parser_exception(e)

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

    def parser_exception(self, exc) -> None:
        pass


def async_callback(func):
    @functools.wraps(func)
    def callback(protocol, *args, **kwargs):
        protocol.loop.create_task(func(protocol, *args, **kwargs))
    return callback
