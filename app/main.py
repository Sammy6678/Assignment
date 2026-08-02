import json
import os
import random
import time
import unicodedata
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(BASE_DIR, "frontend", "index.html")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


ENABLE_DOCS = os.environ.get("ENABLE_DOCS", "false").lower() == "true"
ALLOWED_ORIGINS = [
    origin.strip().rstrip("/").lower()
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
MAX_MESSAGE_LENGTH = _env_int("MAX_MESSAGE_LENGTH", 2000)
MAX_CONNECTIONS = _env_int("MAX_CONNECTIONS", 200)
RATE_LIMIT_MESSAGES = _env_int("RATE_LIMIT_MESSAGES", 10)
RATE_LIMIT_WINDOW_SECONDS = _env_int("RATE_LIMIT_WINDOW_SECONDS", 5)

WS_POLICY_VIOLATION = 1008
WS_TRY_AGAIN_LATER = 1013

app = FastAPI(
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)


@app.get("/")
async def get():
    return FileResponse(INDEX_PATH)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


def is_origin_allowed(origin: str, host_header: str) -> bool:
    """Guard against cross-site WebSocket hijacking.

    Browsers always send an Origin header on WebSocket handshakes, so a request
    without one comes from a non-browser client and cannot carry ambient
    credentials. When no allowlist is configured, only same-origin requests
    (Origin host matching the Host header) are accepted.
    """
    if not origin:
        return True

    normalized = origin.rstrip("/").lower()
    if ALLOWED_ORIGINS:
        return normalized in ALLOWED_ORIGINS

    origin_host = urlparse(normalized).netloc
    return bool(origin_host) and origin_host == (host_header or "").lower()


def sanitize_message(raw: str) -> str:
    """Drop control characters and collapse the payload to a safe length."""
    cleaned = "".join(
        char
        for char in raw
        if char in ("\n", "\t") or unicodedata.category(char)[0] != "C"
    )
    return cleaned.strip()[:MAX_MESSAGE_LENGTH]


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.user_data: Dict[WebSocket, str] = {}
        self.message_times: Dict[WebSocket, Deque[float]] = {}

    async def connect(self, websocket: WebSocket) -> bool:
        if len(self.active_connections) >= MAX_CONNECTIONS:
            await websocket.close(code=WS_TRY_AGAIN_LATER, reason="Server is full")
            return False

        await websocket.accept()
        self.active_connections.append(websocket)
        user_name = f"Guest_{random.randint(1000, 9999)}"
        self.user_data[websocket] = user_name
        self.message_times[websocket] = deque()

        await self.broadcast_system_message(f"{user_name} has joined the chat.")
        await self.send_personal_message(
            f"Welcome to the chat! You are connected as {user_name}.", websocket
        )
        await self.broadcast_stats()
        return True

    def disconnect(self, websocket: WebSocket) -> str:
        user_name = self.user_data.pop(websocket, "Unknown")
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.message_times.pop(websocket, None)
        return user_name

    def is_rate_limited(self, websocket: WebSocket) -> bool:
        now = time.monotonic()
        timestamps = self.message_times.setdefault(websocket, deque())
        while timestamps and now - timestamps[0] > RATE_LIMIT_WINDOW_SECONDS:
            timestamps.popleft()
        if len(timestamps) >= RATE_LIMIT_MESSAGES:
            return True
        timestamps.append(now)
        return False

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(json.dumps({"type": "system", "message": message}))

    async def _broadcast(self, payload_for):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json.dumps(payload_for(connection)))
            except (WebSocketDisconnect, RuntimeError):
                self.disconnect(connection)

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
        await self._broadcast(
            lambda _: {"type": "stats", "count": len(self.active_connections)}
        )


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin", "")
    host_header = websocket.headers.get("host", "")
    if not is_origin_allowed(origin, host_header):
        await websocket.close(code=WS_POLICY_VIOLATION, reason="Origin not allowed")
        return

    if not await manager.connect(websocket):
        return

    try:
        while True:
            data = await websocket.receive_text()
            if len(data) > MAX_MESSAGE_LENGTH:
                await manager.send_personal_message(
                    f"Message rejected: limit is {MAX_MESSAGE_LENGTH} characters.",
                    websocket,
                )
                continue

            if manager.is_rate_limited(websocket):
                await manager.send_personal_message(
                    "You are sending messages too quickly. Please slow down.",
                    websocket,
                )
                continue

            message = sanitize_message(data)
            if not message:
                continue

            await manager.broadcast_chat_message(message, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        user_name = manager.disconnect(websocket)
        await manager.broadcast_system_message(f"{user_name} has left the chat.")
        await manager.broadcast_stats()
