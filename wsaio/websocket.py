import enum
import os
import struct

from .exceptions import ParserInvalidDataError
from .utils import ensure_length


class WebSocketOpcode(enum.IntEnum):
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


CONTROL_OPCODES = (
    WebSocketOpcode.CLOSE,
    WebSocketOpcode.PING,
    WebSocketOpcode.PONG,
)


class WebSocketCloseCode(enum.IntEnum):
    # 0 - 999 NOT USED
    NORMAL_CLOSURE = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    NO_STATUS_RECEIVED = 1005  # (Reserved for "applications")
    ABNORMAL_CLOSURE = 1006  # (Reserved for "applications")
    INVALID_PAYLOAD_DATA = 1007
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    MANDATORY_EXTENSION = 1010
    INTERNAL_SERVER_ERROR = 1011
    TLS_HANDSHAKE = 1015  # (Reserved for "applications")
    # XXX: What's the difference between an application and an endpoint?
    # 1000 - 2999 RESERVED FOR WEBSOCKET PROTOCOL
    # 3000 - 3999 RESERVED FOR LIBRARIES, FRAMEWORKS AND APPS
    # 4000 - 4999 RESERVED FOR PRIVATE USE


class WebSocketFrame:
    SHORT_LENGTH = struct.Struct('!H')
    LONGLONG_LENGTH = struct.Struct('!Q')

    def __init__(self, *, opcode, fin=True, rsv1=False, rsv2=False, rsv3=False, data):
        self.opcode = opcode
        self.fin = fin
        self.rsv1 = rsv1
        self.rsv2 = rsv2
        self.rsv3 = rsv3
        self.data = data

    def __repr__(self):
        attrs = ('fin', 'rsv1', 'rsv2', 'rsv3', 'opcode')
        formatted = ', '.join(f'{name}={getattr(self, name)!r}' for name in attrs)
        return f'<{self.__class__.__name__} {formatted}>'

    @staticmethod
    def apply_mask(data, mask):
        data = bytearray(data)

        for i in range(len(data)):
            data[i] ^= mask[i % 4]

        return data

    def serialize(self, masked=False):
        buffer = bytearray(2)
        buffer[0] = (
            (self.fin << 7)
            | (self.rsv1 << 6)
            | (self.rsv2 << 5)
            | (self.rsv3 << 4)
            | self.opcode
        )
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
            data = self.apply_mask(self.data, mask)
        else:
            data = self.data

        buffer.extend(data)

        return buffer

    @classmethod
    def parser(cls, protocol):
        data = yield
        position = 0
        fragmented_frame = None
        fragment_buffer = bytearray()

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
                opcode=WebSocketOpcode(fbyte & 0xF), fin=(fbyte >> 7) & 1, rsv1=(fbyte >> 6) & 1,
                rsv2=(fbyte >> 5) & 1, rsv3=(fbyte >> 4) & 1, data=payload
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
                        'were negotiated', extra
                    )

            if frame.opcode in CONTROL_OPCODES:
                if len(frame.data) > 125:
                    extra['close_code'] = WebSocketCloseCode.PROTOCOL_ERROR
                    raise ParserInvalidDataError(
                        f'Received control frame with payload length > 125 '
                        f'({len(frame.data)})', extra
                    )

                elif not frame.fin:
                    extra['close_code'] = WebSocketCloseCode.PROTOCOL_ERROR
                    raise ParserInvalidDataError(
                        'Received fragmented control frame', extra
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
                if fragmented_frame is not None:
                    if frame.opcode is not WebSocketOpcode.CONTINUATION:
                        extra['close_code'] = WebSocketCloseCode.PROTOCOL_ERROR
                        raise ParserInvalidDataError(
                            f'Expected opcode {WebSocketOpcode.CONTINUATION} '
                            f'(got {frame.opcode})',
                            extra
                        )
                    else:
                        fragment_buffer.extend(frame.data)
                        if frame.fin:
                            frame = fragmented_frame
                            fragmented_frame = None
                            frame.data = bytes(fragment_buffer)

                elif not frame.fin:
                    fragment_buffer.clear()
                    fragment_buffer.extend(frame.data)
                    fragmented_frame = frame

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
