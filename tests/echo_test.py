import client
import asyncio

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
loop = asyncio.get_event_loop()

URL = 'wss://echo.websocket.org'
client = client.Client(loop=loop, is_ssl=True)


async def main():
    await client.connect(URL)
    await client.send_text('Hello World')
    print(await client.receive_text())

loop.run_until_complete(main())
