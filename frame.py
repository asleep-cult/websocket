import os
from reader import Reader
from typing import Generator


class Frame:
    def __init__(self, **kwargs) -> None:
        self.fin: bool = kwargs.pop('fin', False)
        self.rsv1: bool = kwargs.pop('rsv1', False)
        self.rsv2: bool = kwargs.pop('rsv2', False)
        self.rsv3: bool = kwargs.pop('rsv3', False)
        self.opcode: bool = kwargs.pop('opcode', False)
        self.masked: bool = kwargs.pop('masked', False)
        self.data: bytes = kwargs.pop('data')

    def __repr__(self):
        return \
            'Frame(fin={}, rsv1={}, rsv2={}, rsv3={}, ' \
            'opcode={}, masked={}, data={!r})'.format(
                self.fin, self.rsv1, self.rsv2,
                self.rsv3, self.opcode, self.masked,
                self.data
            )

    @staticmethod
    def _unpack_bits(byte: int) -> Generator[bool, None, None]:
        shift = 7
        while True:
            yield ((byte >> shift) & 1) != 0
            if shift == 0:
                return
            shift -= 1

    @staticmethod
    def _pack_bits(*bits) -> int:
        offset = 0x80
        out = 0
        for bit in bits:
            if bit:
                out |= offset
            offset //= 2
        return out

    @staticmethod
    def _mask_buffer(buffer: bytearray, mask: bytes) -> None:
        for i in range(len(buffer)):
            buffer[i] ^= mask[i % 4]
        return buffer

    @classmethod
    async def create(cls, reader: Reader) -> 'Frame':
        fbyte, = await reader.read_all(1)
        fbyte_bits = iter(cls._unpack_bits(fbyte))

        fin = next(fbyte_bits)
        rsv1 = next(fbyte_bits)
        rsv2 = next(fbyte_bits)
        rsv3 = next(fbyte_bits)
        opcode = fbyte & 0xF

        sbyte, = await reader.read(1)
        sbyte_bits = iter(cls._unpack_bits(sbyte))

        masked = next(sbyte_bits)
        length = sbyte & 0x7F

        if length == 0x7E:
            legnth_bytes = await reader.read_all(2)
            length = int.from_bytes(legnth_bytes, 'big', signed=False)
        elif length == 0x7F:
            legnth_bytes = await reader.read_all(4)
            length = int.from_bytes(legnth_bytes, 'big', signed=False)

        mask = None
        if masked:
            mask = await reader.read_all(4)

        data = bytearray(await reader.read_all(length))

        if masked:
            cls._mask_buffer(data, mask)

        return cls(
            fin=fin, rsv1=rsv1, rsv2=rsv2,
            rsv3=rsv3, opcode=opcode, masked=masked,
            data=data
        )

    def encode(self) -> bytearray:
        buffer = bytearray(2)
        buffer[0] = \
            self._pack_bits(self.fin, self.rsv1, self.rsv2, self.rsv3) \
            | self.opcode

        buffer[1] = self._pack_bits(self.masked)

        length = len(self.data)
        if length < 0x7E:
            buffer[1] |= length
        elif length < 0x10000:
            buffer[1] |= 0x7E
            buffer.extend(length.to_bytes(2, 'big', signed=False))
        else:
            buffer[1] |= 0x7F
            buffer.extend(length.to_bytes(4, 'big', signed=False))

        if self.masked:
            mask = os.urandom(4)
            buffer.extend(mask)
            data = self._mask_buffer(bytearray(self.data), mask)
        else:
            data = self.data

        buffer.extend(data)

        return buffer
