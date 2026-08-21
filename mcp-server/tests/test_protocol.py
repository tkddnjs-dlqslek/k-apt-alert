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


META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "t", "version": "0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _modern(rid, method, **params):
    params["_meta"] = dict(META)
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}


def test_discover_returns_versions_caps_identity():
    resp = server.handle(_modern("d1", "server/discover"))
    r = resp["result"]
    assert r["supportedVersions"] == ["2026-07-28"]
    assert r["capabilities"] == {"tools": {}}
    assert r["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": server.SERVER_NAME, "version": server.SERVER_VERSION}


def test_modern_unsupported_version_returns_32022():
    msg = _modern(10, "tools/list")
    msg["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "1900-01-01"
    resp = server.handle(msg)
    assert resp["error"]["code"] == -32022
    assert resp["error"]["data"] == {"supported": ["2026-07-28"], "requested": "1900-01-01"}


def test_modern_missing_client_capabilities_returns_32602():
    msg = _modern(11, "tools/list")
    del msg["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]
    resp = server.handle(msg)
    assert resp["error"]["code"] == -32602


def test_modern_tools_call_dispatches(monkeypatch):
    monkeypatch.setitem(server.HANDLERS, "list_categories", lambda a: {"ok": True})
    resp = server.handle(_modern(12, "tools/call", name="list_categories", arguments={}))
    assert '"ok": true' in resp["result"]["content"][0]["text"]


def test_discover_without_meta_is_still_answered():
    """Legacy 클라이언트가 보낸 server/discover에도 답해야 Dual-era 클라이언트 프로브가 동작."""
    resp = server.handle({"jsonrpc": "2.0", "id": 13, "method": "server/discover"})
    assert resp["result"]["supportedVersions"] == ["2026-07-28"]


def test_every_result_has_result_type_and_server_info():
    for msg in (LEGACY_INIT,
                {"jsonrpc": "2.0", "id": 20, "method": "tools/list"},
                _modern(21, "tools/list"),
                _modern(22, "server/discover")):
        r = server.handle(msg)["result"]
        assert r["resultType"] == "complete", msg["method"]
        assert r["_meta"]["io.modelcontextprotocol/serverInfo"] == server.SERVER_INFO, msg["method"]


def test_tools_list_is_cacheable_and_deterministic():
    a = server.handle(_modern(30, "tools/list"))["result"]
    b = server.handle(_modern(31, "tools/list"))["result"]
    assert a["ttlMs"] == 3600000 and a["cacheScope"] == "public"
    assert [t["name"] for t in a["tools"]] == [t["name"] for t in b["tools"]]


def test_tool_error_result_keeps_is_error_and_result_type(monkeypatch):
    def boom(a):
        raise RuntimeError("x")
    monkeypatch.setitem(server.HANDLERS, "list_categories", boom)
    r = server.handle(_modern(40, "tools/call", name="list_categories", arguments={}))["result"]
    assert r["isError"] is True and r["resultType"] == "complete"
