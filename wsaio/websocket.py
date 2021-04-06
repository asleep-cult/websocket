from __future__ import annotations

import enum
import os
import struct
from typing import ByteString

from .utils import ensure_length


class WebSocketProtocol:
    def ws_connected(self) -> None:
        pass

    def ws_frame_received(self, frame: WebSocketFrame) -> None:
        pass


class WebSocketOpcode(enum.IntEnum):
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


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
