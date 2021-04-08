from __future__ import annotations

import enum
import os
import struct
from typing import ByteString

from .exceptions import ParserInvalidDataError
from .protocol import BaseProtocol
from .utils import ensure_length


class WebSocketOpcode(enum.IntEnum):
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


class WebSocketCloseCode(enum.IntEnum):
    # 0 - 999 NOT USED
    NORMAL_CLOSURE = 1000  # Server <-> Client
    GOING_AWAY = 1001  # Server <-> Client
    PROTOCOL_ERROR = 1002  # Server <-> Client
    UNSUPPORTED_DATA = 1003  # Server <-> Client
    NO_STATUS_RECEIVED = 1005  # Server ~ Client (Reserved for "applications")
    ABNORMAL_CLOSURE = 1006  # Server ~ Client (Reserved for "applications")
    INVALID_PAYLOAD_DATA = 1007  # Server <-> Client
    POLICY_VIOLATION = 1008  # Server <-> Client
    MESSAGE_TOO_BIG = 1009  # Server <-> Client
    MANDATORY_EXTENSION = 1010  # Server <-(>?) Client
    INTERNAL_SERVER_ERROR = 1011  # Server -> Client
    TLS_HANDSHAKE = 1015  # Server ~ Client (Reserved for "applications")
    # XXX: What's the difference between an application and an endpoint?
    # 1000 - 2999 RESERVED FOR WEBSOCKET PROTOCOL
    # 3000 - 3999 RESERVED FOR LIBRARIES, FRAMEWORKS AND APPS
    # 4000 - 4999 RESERVED FOR PRIVATE USE


class WebSocketState(enum.IntEnum):
    HANDSHAKING = 4


class WebSocketProtocol:
    def __init__(self):
        self.extensions = []

    def strstate(self):
        strstate = BaseProtocol.strstate(self)
        if strstate is not None:
            return strstate
        elif self.state is WebSocketState.HANDSHAKING:
            return 'handshaking'

    def ws_connected(self) -> None:
        pass

    def ws_frame_received(self, frame: WebSocketFrame) -> None:
        pass

    def ws_binary_received(self, data: bytes) -> None:
        pass

    def ws_text_received(self, data: str) -> None:
        pass

    def ws_ping_received(self, data: bytes) -> None:
        pass

    def ws_pong_received(self, data: bytes) -> None:
        pass

    def ws_close_received(self, code: int, data: bytes) -> None:
        pass


class WebSocketFrame:
    SHORT_LENGTH = struct.Struct('!H')
    LONGLONG_LENGTH = struct.Struct('!Q')

    def __init__(
        self, *, opcode: WebSocketOpcode, fin: bool = True,
        rsv1: bool = False, rsv2: bool = False, rsv3: bool = False,
        data: ByteString
    ):
        self.opcode = opcode
        self.fin = fin
        self.rsv1 = rsv1
        self.rsv2 = rsv2
        self.rsv3 = rsv3
        self.data = data

    def __repr__(self) -> str:
        attrs = ('fin', 'rsv1', 'rsv2', 'rsv3', 'opcode')
        s = ', '.join(f'{name}={getattr(self, name)!r}' for name in attrs)
        return f'<{self.__class__.__name__} {s}>'

    @staticmethod
    def mask(data: ByteString, mask: bytes) -> bytearray:
        data = bytearray(data)
        for i in range(len(data)):
            data[i] ^= mask[i % 4]
        return data

    def encode(self, masked: bool = False) -> bytearray:
        buffer = bytearray(2)
        buffer[0] = ((self.fin << 7)
                     | (self.rsv1 << 6)
                     | (self.rsv2 << 5)
                     | (self.rsv3 << 4)
                     | self.opcode)
        buffer[1] = masked << 7

        length = len(self.data)
        if length < 126:
            buffer[1] |= length
        elif length < 2 ** 16:
            buffer[1] |= 126
            buffer.extend(self.SHORT_LENGTH.pack(length))
        else:
            buffer[1] |= 127
            buffer.extend(self.LONGLONG_LENGTH.pack(length))

        if masked:
            mask = os.urandom(4)
            buffer.extend(mask)
            data = self.mask(self.data, mask)
        else:
            data = self.data

        buffer.extend(data)

        return buffer

    @classmethod
    def parser(cls, protocol: WebSocketProtocol):
        data = yield
        position = 0
        fragments = []

        while True:
            data = data[position:]
            position = 0

            data = yield from ensure_length(data, position + 1)
            fbyte = data[position]
            position += 1

            data = yield from ensure_length(data, position + 1)
            sbyte = data[position]
            position += 1

            masked = (sbyte >> 7) & 1
            length = sbyte & ~(1 << 7)

            if length > 125:
                if length == 126:
                    strct = cls.SHORT_LENGTH
                elif length == 127:
                    strct = cls.LONGLONG_LENGTH

                data = yield from ensure_length(data, position + strct.size)
                length, = strct.unpack_from(data, position)
                position += strct.size

            if masked:
                data = yield from ensure_length(data, position + 4)
                mask = data[position:position + 4]
                position += 4

            data = yield from ensure_length(data, position + length)
            payload = data[position:position + length]
            position += length

            if masked:
                payload = cls.mask(data, mask)

            frame = cls(
                opcode=WebSocketOpcode(fbyte & 0xF),
                fin=(fbyte >> 7) & 1, rsv1=(fbyte >> 6) & 1,
                rsv2=(fbyte >> 5) & 1, rsv3=(fbyte >> 4) & 1,
                data=payload
            )
            protocol.ws_frame_received(frame)

            extra = {
                'frame': frame,
                'protocol': protocol
            }

            if not protocol.extensions:
                if any((frame.rsv1, frame.rsv2, frame.rsv3)):
                    extra['close_code'] = WebSocketCloseCode.PROTOCOL_ERROR
                    raise ParserInvalidDataError(
                        'Received rsv1, rsv2 or rsv3 but no extensions '
                        'were negotiated',
                        extra
                    )

            control = (frame.opcode >> 7) & 1

            if control:
                if len(frame.data) > 125:
                    extra['close_code'] = WebSocketCloseCode.PROTOCOL_ERROR
                    raise ParserInvalidDataError(
                        'Received control frame with payload length > 125 '
                        f'({len(frame.data)})',
                        extra
                    )
                elif not frame.fin:
                    extra['close_code'] = WebSocketCloseCode.PROTOCOL_ERROR
                    raise ParserInvalidDataError(
                        'Received fragmented control frame',
                        extra
                    )
                elif frame.opcode is WebSocketOpcode.PING:
                    protocol.ws_ping_received(frame.data)
                elif frame.opcode is WebSocketOpcode.PONG:
                    protocol.ws_pong_received(frame.data)
                elif frame.opcode is WebSocketOpcode.CLOSE:
                    close_clode = int.from_bytes(frame.data[:2], 'big')
                    data = frame.data[2:]
                    protocol.ws_close_received(close_clode, data)
            else:
                if fragments:
                    if frame.opcode is not WebSocketOpcode.CONTINUATION:
                        extra['close_code'] = WebSocketCloseCode.PROTOCOL_ERROR
                        raise ParserInvalidDataError(
                            f'Expected opcode {WebSocketOpcode.CONTINUATION} '
                            f'(got {frame.opcode})',
                            extra
                        )
                    else:
                        fragments.append(frame)
                        if frame.fin:
                            frame = fragments[0]
                            frame.data = b''.join(f.data for f in fragments)
                            fragments = []
                elif not frame.fin:
                    fragments.append(frame)
                    continue

                if frame.opcode is WebSocketOpcode.TEXT:
                    try:
                        string = frame.data.decode()
                    except UnicodeDecodeError as e:
                        extra['close_code'] = (
                            WebSocketCloseCode.INVALID_PAYLOAD_DATA
                        )
                        raise ParserInvalidDataError(str(e), extra)
                    protocol.ws_text_received(string)
                elif frame.opcode is WebSocketOpcode.BINARY:
                    protocol.ws_binary_received(frame.data)
