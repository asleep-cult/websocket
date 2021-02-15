import asyncio
import socket
import reader
import frame

loop = asyncio.get_event_loop()

rsock, ssock = socket.socketpair()
rsock = reader.Reader(loop, rsock)


data = frame.Frame(
    fin=False, rsv1=False, rsv2=False,
    rsv3=False, opcode=0x01, masked=False,
    data=bytearray('Hello World' * 100, 'ascii')
).encode()
print(data)

ssock.send(data)


async def main():
    f = await frame.Frame.create(rsock)
    print(f)

asyncio.run(main())
