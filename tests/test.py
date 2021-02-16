import asyncio
import socket
import reader
import frame
import time

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
loop = asyncio.get_event_loop()

rsock, ssock = socket.socketpair()
rsock = reader.Reader(loop, rsock)


f = frame.Frame(
    opcode=0x01, masked=True,
    data=bytearray('Hello World', 'ascii')
).encode()

for _ in range(20):
    ssock.send(f)


async def main():
    start = time.perf_counter()
    for _ in range(10):
        f = await frame.Frame.create(rsock)
        assert f.data.decode() == 'Hello World'
    print(f'Finished in: {round((time.perf_counter() - start) * 1000)}ms')


loop.run_until_complete(main())
