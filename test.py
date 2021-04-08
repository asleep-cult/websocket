import asyncio
import itertools

import wsaio

URL = 'wss://echo.websocket.org'


class HelloClient(wsaio.WebSocketClient):
    @wsaio.taskify
    async def ws_connected(self):
        for i in itertools.count():
            print(f'[HelloClient] Sending data - COUNT: {i}')
            await self.send_str('Hello World')
            await asyncio.sleep(5)

    def ws_text_received(self, data):
        print(f'[HelloClient] Received frame - DATA: {data}')

    def closing_connection(self, exc):
        print(f'[HelloClient] Closed while {self.strstate()}', str(exc))


client = HelloClient()
client.loop.create_task(client.connect(URL))
client.loop.run_forever()
