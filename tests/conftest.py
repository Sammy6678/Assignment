import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import main  # noqa: E402


@pytest.fixture(autouse=True)
def clean_manager():
    """Reset the module-level ConnectionManager state around every test."""
    main.manager.active_connections.clear()
    main.manager.user_data.clear()
    yield
    main.manager.active_connections.clear()
    main.manager.user_data.clear()


class FakeWebSocket:
    """Minimal WebSocket stand-in that records the frames sent to it."""

    def __init__(self):
        self.accepted = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def send_text(self, text):
        self.sent.append(text)


@pytest.fixture
def fake_websocket():
    return FakeWebSocket()
