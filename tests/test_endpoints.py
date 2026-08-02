import json

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_root_serves_the_frontend_page():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text.lower()


def test_favicon_returns_no_content():
    response = client.get("/favicon.ico")

    assert response.status_code == 204
    assert response.content == b""


def test_websocket_handshake_sends_join_welcome_and_stats():
    with client.websocket_connect("/ws") as websocket:
        joined = websocket.receive_json()
        welcome = websocket.receive_json()
        stats = websocket.receive_json()

    assert joined["type"] == "system"
    assert joined["message"].endswith("has joined the chat.")
    user_name = joined["message"].split(" ")[0]
    assert welcome == {
        "type": "system",
        "message": f"Welcome to the chat! You are connected as {user_name}.",
    }
    assert stats == {"type": "stats", "count": 1}


def test_websocket_broadcasts_chat_messages_to_all_clients():
    with client.websocket_connect("/ws") as first:
        first_name = first.receive_json()["message"].split(" ")[0]
        first.receive_json()
        first.receive_json()

        with client.websocket_connect("/ws") as second:
            first.receive_json()  # join announcement
            assert first.receive_json() == {"type": "stats", "count": 2}
            second.receive_json()
            second.receive_json()
            second.receive_json()

            first.send_text("hello everyone")

            for websocket, is_self in ((first, True), (second, False)):
                message = websocket.receive_json()
                assert message["type"] == "chat"
                assert message["username"] == first_name
                assert message["message"] == "hello everyone"
                assert message["isSelf"] is is_self


def test_websocket_disconnect_announces_departure_and_updates_stats():
    with client.websocket_connect("/ws") as first:
        for _ in range(3):
            first.receive_json()

        with client.websocket_connect("/ws") as second:
            second_name = second.receive_json()["message"].split(" ")[0]
            second.receive_json()
            second.receive_json()
            first.receive_json()
            first.receive_json()

        assert first.receive_json() == {
            "type": "system",
            "message": f"{second_name} has left the chat.",
        }
        assert first.receive_json() == {"type": "stats", "count": 1}

    assert main.manager.active_connections == []


def test_websocket_relays_non_text_payloads_as_plain_strings():
    with client.websocket_connect("/ws") as websocket:
        for _ in range(3):
            websocket.receive_json()

        websocket.send_text(json.dumps({"nested": "payload"}))

        assert websocket.receive_json()["message"] == '{"nested": "payload"}'
