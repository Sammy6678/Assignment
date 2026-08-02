import json
import re

import pytest

import main
from conftest import FakeWebSocket


def payloads(websocket):
    return [json.loads(frame) for frame in websocket.sent]


@pytest.mark.asyncio
async def test_connect_accepts_registers_and_greets():
    websocket = FakeWebSocket()

    await main.manager.connect(websocket)

    assert websocket.accepted is True
    assert main.manager.active_connections == [websocket]

    user_name = main.manager.user_data[websocket]
    assert re.fullmatch(r"Guest_\d{4}", user_name)

    joined, welcome, stats = payloads(websocket)
    assert joined == {"type": "system", "message": f"{user_name} has joined the chat."}
    assert welcome == {
        "type": "system",
        "message": f"Welcome to the chat! You are connected as {user_name}.",
    }
    assert stats == {"type": "stats", "count": 1}


@pytest.mark.asyncio
async def test_connect_announces_new_user_to_existing_clients():
    first = FakeWebSocket()
    second = FakeWebSocket()

    await main.manager.connect(first)
    first.sent.clear()
    await main.manager.connect(second)

    second_name = main.manager.user_data[second]
    assert payloads(first) == [
        {"type": "system", "message": f"{second_name} has joined the chat."},
        {"type": "stats", "count": 2},
    ]
    assert main.manager.active_connections == [first, second]


@pytest.mark.asyncio
async def test_disconnect_removes_connection_and_returns_user_name():
    websocket = FakeWebSocket()
    await main.manager.connect(websocket)
    user_name = main.manager.user_data[websocket]

    assert main.manager.disconnect(websocket) == user_name
    assert main.manager.active_connections == []
    assert main.manager.user_data == {}


def test_disconnect_unknown_websocket_is_a_noop():
    websocket = FakeWebSocket()

    assert main.manager.disconnect(websocket) == "Unknown"
    assert main.manager.active_connections == []
    assert main.manager.user_data == {}


def test_disconnect_untracked_but_connected_websocket():
    websocket = FakeWebSocket()
    main.manager.active_connections.append(websocket)

    assert main.manager.disconnect(websocket) == "Unknown"
    assert main.manager.active_connections == []


@pytest.mark.asyncio
async def test_send_personal_message_targets_single_client():
    recipient = FakeWebSocket()
    bystander = FakeWebSocket()
    main.manager.active_connections.extend([recipient, bystander])

    await main.manager.send_personal_message("hello", recipient)

    assert payloads(recipient) == [{"type": "system", "message": "hello"}]
    assert bystander.sent == []


@pytest.mark.asyncio
async def test_broadcast_chat_message_marks_the_sender():
    sender = FakeWebSocket()
    other = FakeWebSocket()
    main.manager.active_connections.extend([sender, other])
    main.manager.user_data[sender] = "Guest_1234"

    await main.manager.broadcast_chat_message("hi there", sender)

    for websocket, is_self in ((sender, True), (other, False)):
        (message,) = payloads(websocket)
        assert message["type"] == "chat"
        assert message["username"] == "Guest_1234"
        assert message["message"] == "hi there"
        assert message["isSelf"] is is_self
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2} (AM|PM)", message["time"])


@pytest.mark.asyncio
async def test_broadcast_chat_message_from_untracked_sender():
    sender = FakeWebSocket()
    main.manager.active_connections.append(sender)

    await main.manager.broadcast_chat_message("hi", sender)

    assert payloads(sender)[0]["username"] == "Unknown"


@pytest.mark.asyncio
async def test_broadcast_system_message_reaches_every_client():
    clients = [FakeWebSocket() for _ in range(3)]
    main.manager.active_connections.extend(clients)

    await main.manager.broadcast_system_message("server restarting")

    for client in clients:
        assert payloads(client) == [{"type": "system", "message": "server restarting"}]


@pytest.mark.asyncio
async def test_broadcast_stats_reports_the_connection_count():
    clients = [FakeWebSocket() for _ in range(2)]
    main.manager.active_connections.extend(clients)

    await main.manager.broadcast_stats()

    for client in clients:
        assert payloads(client) == [{"type": "stats", "count": 2}]


@pytest.mark.asyncio
async def test_broadcasts_with_no_connections_are_safe():
    await main.manager.broadcast_system_message("nobody is listening")
    await main.manager.broadcast_stats()

    assert main.manager.active_connections == []
