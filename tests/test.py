import asyncio
import socket
import client
import frame
import time

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
loop = asyncio.get_event_loop()

rsock, ssock = socket.socketpair()

c = client.Client(loop=loop, sock=rsock)
s = client.Client(loop=loop, sock=ssock)


async def main():
    start = time.perf_counter()
    for _ in range(10):
        await c.send_frame(
            frame.Frame(
                masked=True, data=b'Hello World HI'
            )
        )
    print(f'Finished in: {round((time.perf_counter() - start) * 1000)}ms')

    start = time.perf_counter()
    for _ in range(10):
        assert (await s.receive_text()) == 'Hello World HI'
    print(f'Finished in: {round((time.perf_counter() - start) * 1000)}ms')


loop.run_until_complete(main())
