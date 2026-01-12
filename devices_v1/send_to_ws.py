import json
import websockets

from configs import WS_URL


async def send_to_ws(event: str, data: dict | None = None):
    message = {"event": event, "data": data}
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps(message))
        print(f"Отправлено: {message}")
