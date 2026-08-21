"""server.py JSON-RPC 디스패치 테스트. 네트워크 없음: HANDLERS를 monkeypatch."""

import server

LEGACY_INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "t", "version": "0"}},
}


def test_legacy_initialize_echoes_version():
    resp = server.handle(LEGACY_INIT)
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert resp["result"]["capabilities"] == {"tools": {}}
    assert resp["result"]["serverInfo"]["name"] == server.SERVER_NAME


def test_legacy_initialized_notification_is_silent():
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_legacy_ping():
    resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert "result" in resp and "error" not in resp


def test_legacy_tools_list_returns_all_tools():
    resp = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert [t["name"] for t in resp["result"]["tools"]] == [t["name"] for t in server.TOOLS]


def test_legacy_tools_call_dispatches(monkeypatch):
    monkeypatch.setitem(server.HANDLERS, "list_categories", lambda a: {"ok": True})
    resp = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                          "params": {"name": "list_categories", "arguments": {}}})
    assert '"ok": true' in resp["result"]["content"][0]["text"]


def test_unknown_method_returns_32601():
    resp = server.handle({"jsonrpc": "2.0", "id": 5, "method": "nope"})
    assert resp["error"]["code"] == -32601
