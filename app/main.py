from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Any, Callable, Dict, List
import json
import os
import random
from datetime import datetime
from fastapi.responses import FileResponse, Response

app = FastAPI()


def system_payload(message: str) -> Dict[str, Any]:
    return {"type": "system", "message": message}


@app.get("/")
async def get():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    index_path = os.path.join(base_dir, "frontend", "index.html")
    return FileResponse(index_path)

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
        
        # Broadcast connection
        await self.broadcast_system_message(f"{user_name} has joined the chat.")
        await self.send_personal_message(f"Welcome to the chat! You are connected as {user_name}.", websocket)
        await self.broadcast_stats()

    def disconnect(self, websocket: WebSocket):
        user_name = self.user_data.get(websocket, "Unknown")
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.user_data:
            del self.user_data[websocket]
        return user_name

    async def send_payload(self, payload: Dict[str, Any], websocket: WebSocket):
        await websocket.send_text(json.dumps(payload))

    async def broadcast_payload(self, build_payload: Callable[[WebSocket], Dict[str, Any]]):
        for connection in self.active_connections:
            await self.send_payload(build_payload(connection), connection)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await self.send_payload(system_payload(message), websocket)

    async def broadcast_chat_message(self, message: str, sender: WebSocket):
        sender_name = self.user_data.get(sender, "Unknown")
        cur_time = datetime.now().strftime("%I:%M:%S %p")
        await self.broadcast_payload(lambda connection: {
            "type": "chat",
            "username": sender_name,
            "message": message,
            "time": cur_time,
            "isSelf": sender == connection
        })

    async def broadcast_system_message(self, message: str):
        await self.broadcast_payload(lambda connection: system_payload(message))

    async def broadcast_stats(self):
        await self.broadcast_payload(lambda connection: {
            "type": "stats",
            "count": len(self.active_connections)
        })

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast_chat_message(data, websocket)
    except WebSocketDisconnect:
        user_name = manager.disconnect(websocket)
        await manager.broadcast_system_message(f"{user_name} has left the chat.")
        await manager.broadcast_stats()
