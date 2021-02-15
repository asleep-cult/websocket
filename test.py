import asyncio
import socket
import reader
import frame

loop = asyncio.get_event_loop()

rsock, ssock = socket.socketpair()
rsock = reader.Reader(loop, rsock)


f = frame.Frame(
    opcode=0x01, masked=True,
    data=bytearray('Hello World', 'ascii')
)
print(f)

ssock.send(f.encode())


async def main():
    f = await frame.Frame.create(rsock)
    print(f)

asyncio.run(main())
