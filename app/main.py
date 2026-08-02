from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from typing import List
import json
import logging
import os
import random
from datetime import datetime

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("chat")

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(BASE_DIR, "frontend", "index.html")


@app.get("/")
async def get():
    if not os.path.isfile(INDEX_PATH):
        logger.error("Frontend entrypoint is missing: %s", INDEX_PATH)
        raise HTTPException(status_code=500, detail="Frontend index.html is not available.")
    return FileResponse(INDEX_PATH)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.user_data = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        user_name = f"Guest_{random.randint(1000, 9999)}"
        self.user_data[websocket] = user_name

        await self.broadcast_system_message(f"{user_name} has joined the chat.")
        await self.send_personal_message(
            f"Welcome to the chat! You are connected as {user_name}.", websocket
        )
        await self.broadcast_stats()
        return user_name

    def disconnect(self, websocket: WebSocket):
        user_name = self.user_data.pop(websocket, "Unknown")
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        return user_name

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await self._send(websocket, {"type": "system", "message": message})

    async def broadcast_chat_message(self, message: str, sender: WebSocket):
        sender_name = self.user_data.get(sender, "Unknown")
        cur_time = datetime.now().strftime("%I:%M:%S %p")
        await self._broadcast(
            lambda connection: {
                "type": "chat",
                "username": sender_name,
                "message": message,
                "time": cur_time,
                "isSelf": sender == connection,
            }
        )

    async def broadcast_system_message(self, message: str):
        await self._broadcast(lambda _: {"type": "system", "message": message})

    async def broadcast_stats(self):
        count = len(self.active_connections)
        await self._broadcast(lambda _: {"type": "stats", "count": count})

    async def _broadcast(self, payload_for):
        """Send to every client, dropping the ones that fail instead of aborting."""
        failed = []
        for connection in list(self.active_connections):
            if not await self._send(connection, payload_for(connection)):
                failed.append(connection)
        for connection in failed:
            self.disconnect(connection)

    async def _send(self, websocket: WebSocket, payload: dict) -> bool:
        """Return True when the payload was handed to the socket."""
        try:
            await websocket.send_text(json.dumps(payload))
            return True
        except (WebSocketDisconnect, RuntimeError, ConnectionError) as exc:
            logger.warning(
                "Dropping client %s: %s", self.user_data.get(websocket, "Unknown"), exc
            )
            return False


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    user_name = await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast_chat_message(data, websocket)
    except WebSocketDisconnect:
        logger.info("%s disconnected.", user_name)
    except Exception:
        logger.exception("Unexpected error on the connection for %s.", user_name)
        raise
    finally:
        manager.disconnect(websocket)
        await manager.broadcast_system_message(f"{user_name} has left the chat.")
        await manager.broadcast_stats()
