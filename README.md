# wsaio
An event-driven WebSocket library for Python built on top of asyncio's protocols.

```py
import asyncio
import itertools

import wsaio

URL = 'wss://echo.websocket.org'


class HelloClient(wsaio.WebSocketClient):
    @wsaio.async_callback
    async def ws_connected(self):
        for i in itertools.count():
            print(f'[HelloClient] Sending data - COUNT: {i}')
            await self.send_str('Hello World')
            await asyncio.sleep(5)

    def ws_frame_received(self, frame):
        print(f'[HelloClient] Received frame - DATA: {frame.data}')


client = HelloClient()
client.loop.create_task(client.connect(URL))
client.loop.run_forever()
```
