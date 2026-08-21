# MCP Dual-era 서버 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mcp-server/server.py`를 MCP 스펙 `2026-07-28`(Modern, stateless)과 기존 `initialize` 핸드셰이크(Legacy) 양쪽을 동시에 처리하는 dual-era 서버로 올린다.

**Architecture:** 요청 `params._meta`에 `io.modelcontextprotocol/protocolVersion`이 있으면 Modern 경로(버전 검증 후 dispatch), 없으면 기존 Legacy 경로. 공통 dispatch는 하나. 모든 result에 `resultType: "complete"`와 `_meta.serverInfo`를 붙이고, `tools/list`에 `ttlMs`와 `cacheScope`를 추가한다. Legacy 클라이언트는 모르는 필드를 무시하므로 공통 적용 가능.

**Tech Stack:** Python 3.8+ stdlib만 (의존성 0 유지). 테스트는 pytest (`proxy/requirements-dev.txt`에 이미 있음).

**Spec:** https://modelcontextprotocol.io/specification/2026-07-28/changelog , https://modelcontextprotocol.io/specification/2026-07-28/server/discover , https://modelcontextprotocol.io/specification/2026-07-28/basic/index#meta , https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio#backward-compatibility

## Global Constraints

- 외부 의존성 추가 금지. `server.py`는 stdlib만 import.
- Python 3.8 호환 유지 (`from __future__ import annotations` 이미 있음, `match` 문 금지, `str | None`은 어노테이션에서만).
- `initialize`, `notifications/initialized`, `ping` 경로 그대로 유지. Claude Code가 아직 Legacy 클라이언트.
- Modern 필수 `_meta` 키 (정확한 문자열):
  - `io.modelcontextprotocol/protocolVersion` (필수)
  - `io.modelcontextprotocol/clientCapabilities` (필수)
  - `io.modelcontextprotocol/clientInfo` (선택)
  - 응답: `io.modelcontextprotocol/serverInfo`
- 에러 코드: 미지원 버전 `-32022` (`data: {"supported": [...], "requested": "..."}`), 필수 `_meta` 누락 `-32602`.
- Modern 지원 버전 목록: `["2026-07-28"]`.
- 커밋 메시지 한국어, 타입 접두어(`feat:`, `test:`, `ci:`, `docs:`) 사용. 기존 로그 참고: `refactor(notice_raw): ...`.
- 문서(README) 한국어. em dash 금지, 나열은 쉼표와 "와/과".

---

## File Structure

| 파일 | 역할 |
|---|---|
| `mcp-server/server.py` (수정) | 디스패치에 Modern 경로 추가. 구조 변경 없이 `handle()` 내부와 `_result()`/`_error()` 헬퍼만 확장 |
| `mcp-server/tests/__init__.py` (생성, 빈 파일) | 패키지 마커 |
| `mcp-server/tests/conftest.py` (생성) | `mcp-server/`를 `sys.path`에 추가해 `import server` 가능하게 |
| `mcp-server/tests/test_protocol.py` (생성) | Legacy 경로 회귀 + Modern 경로 신규 테스트. 네트워크 없음 (`HANDLERS` monkeypatch) |
| `.github/workflows/test.yml` (수정) | pytest-suite job에 `mcp-server` 테스트 스텝 추가 |
| `README.md` (수정) | 293행 근처 mcp-server 설명에 dual-era 한 줄 |
| `.claude-plugin/plugin.json`, `server.py` `SERVER_VERSION` (수정) | `1.0.0` → `1.1.0` |

테스트 실행 기준 디렉토리: `mcp-server/` (CI의 proxy job과 동일 패턴, `working-directory` 지정).

---

### Task 1: 테스트 스캐폴드 + Legacy 회귀 테스트

**Files:**
- Create: `mcp-server/tests/__init__.py`
- Create: `mcp-server/tests/conftest.py`
- Create: `mcp-server/tests/test_protocol.py`

**Interfaces:**
- Consumes: `server.handle(msg: dict) -> dict | None`, `server.HANDLERS: dict[str, callable]`, `server.TOOLS: list`, `server.SERVER_NAME`, `server.SERVER_VERSION`
- Produces: `tests/conftest.py`의 `sys.path` 보정. 이후 Task 테스트는 모두 이 파일에 추가.

- [ ] **Step 1: 빈 패키지 마커 생성**

```bash
cd "C:/Users/user/Desktop/k-apt-alert" && mkdir -p mcp-server/tests && : > mcp-server/tests/__init__.py
```

- [ ] **Step 2: conftest 작성**

`mcp-server/tests/conftest.py`:

```python
"""mcp-server 테스트 공통 설정. `import server`가 되도록 mcp-server/를 sys.path에 추가."""

import sys
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parent.parent
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))
```

- [ ] **Step 3: Legacy 회귀 테스트 작성 (현재 동작 고정)**

`mcp-server/tests/test_protocol.py`:

```python
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
```

- [ ] **Step 4: 실행, 전부 PASS 확인 (코드 변경 전이므로 통과해야 함)**

Run: `cd "C:/Users/user/Desktop/k-apt-alert/mcp-server" && python -m pytest -q`
Expected: `6 passed`

- [ ] **Step 5: 커밋**

```bash
cd "C:/Users/user/Desktop/k-apt-alert" && git add mcp-server/tests && git commit -m "test(mcp-server): Legacy JSON-RPC 경로 회귀 테스트 추가 (dual-era 전환 전 안전망)"
```

---

### Task 2: Modern 경로: `server/discover` + `_meta` 버전 협상

**Files:**
- Modify: `mcp-server/server.py:34-38` (상수 영역), `mcp-server/server.py:276-282` (`_result`/`_error`), `mcp-server/server.py:288-345` (`handle`)
- Test: `mcp-server/tests/test_protocol.py` (추가)

**Interfaces:**
- Produces:
  - 상수 `MODERN_VERSIONS = ["2026-07-28"]`, `META_VER`, `META_CAPS`, `META_SERVER`
  - `_error(rid, code, message, data=None)` (data 인자 추가, 기존 호출부 호환)
  - `_check_modern(params) -> dict | None`: `_meta`에 protocolVersion이 있으면 검증. 문제 있으면 error 응답 dict 반환, 정상이거나 Legacy 요청이면 `None`
  - `handle()`이 `server/discover` 처리
- Consumes: Task 1 테스트 스캐폴드

- [ ] **Step 1: 실패 테스트 추가**

`mcp-server/tests/test_protocol.py` 끝에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd "C:/Users/user/Desktop/k-apt-alert/mcp-server" && python -m pytest -q`
Expected: 5 failed (`KeyError: 'result'` 또는 `-32601`), 6 passed

- [ ] **Step 3: 상수 추가**

`server.py` 36~38행 (`SERVER_VERSION`, `DEFAULT_PROTOCOL`, `UA` 근처) 아래에 추가:

```python
# ── MCP 2026-07-28 (Modern, stateless) ──
# Modern 클라이언트는 initialize 대신 요청마다 _meta에 버전·capabilities를 싣는다.
# Legacy(initialize 핸드셰이크) 경로는 그대로 유지 → dual-era 서버.
MODERN_VERSIONS = ["2026-07-28"]
META_VER = "io.modelcontextprotocol/protocolVersion"
META_CAPS = "io.modelcontextprotocol/clientCapabilities"
META_SERVER = "io.modelcontextprotocol/serverInfo"
SERVER_INFO = {"name": SERVER_NAME, "version": SERVER_VERSION}
```

- [ ] **Step 4: `_error`에 data 인자, `_check_modern` 추가**

`server.py` `_error` 정의를 교체하고 그 아래에 `_check_modern` 추가:

```python
def _error(rid, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def _check_modern(rid, params: dict):
    """Modern(_meta 동봉) 요청 검증. 오류면 error 응답 dict, 정상이거나 Legacy면 None."""
    meta = params.get("_meta") or {}
    if META_VER not in meta:
        return None  # Legacy 요청 → 기존 경로
    ver = meta[META_VER]
    if ver not in MODERN_VERSIONS:
        return _error(rid, -32022, "Unsupported protocol version",
                      {"supported": MODERN_VERSIONS, "requested": ver})
    if META_CAPS not in meta:
        return _error(rid, -32602, f"Invalid params: missing _meta[{META_CAPS}]")
    return None
```

- [ ] **Step 5: `handle()`에 Modern 검증과 `server/discover` 삽입**

`handle()` 안 `if method == "initialize":` 바로 위에 추가:

```python
    if rid is not None:
        bad = _check_modern(rid, params)
        if bad:
            return bad

    if method == "server/discover":
        return _result(rid, {
            "supportedVersions": MODERN_VERSIONS,
            "capabilities": {"tools": {}},
            "_meta": {META_SERVER: SERVER_INFO},
            "instructions": "한국 청약 공고 조회·가점 계산·알림 발송 툴 7종. 먼저 search_announcements로 캐시를 채운 뒤 get_competition을 호출할 것.",
            "ttlMs": 3600000,
            "cacheScope": "public",
        })
```

- [ ] **Step 6: 통과 확인**

Run: `cd "C:/Users/user/Desktop/k-apt-alert/mcp-server" && python -m pytest -q`
Expected: `11 passed`

- [ ] **Step 7: 커밋**

```bash
cd "C:/Users/user/Desktop/k-apt-alert" && git add mcp-server && git commit -m "feat(mcp-server): MCP 2026-07-28 dual-era 대응 — server/discover + _meta 버전 협상(-32022/-32602), Legacy initialize 경로 유지"
```

---

### Task 3: 응답 봉투: `resultType`, `_meta.serverInfo`, `tools/list` 캐시 필드

**Files:**
- Modify: `mcp-server/server.py` (`_result`, `handle`의 `tools/list` 분기)
- Test: `mcp-server/tests/test_protocol.py` (추가)

**Interfaces:**
- Consumes: Task 2의 `META_SERVER`, `SERVER_INFO`
- Produces: 모든 `_result()` 반환값에 `result.resultType == "complete"`, `result._meta[META_SERVER]`. `tools/list` result에 `ttlMs: 3600000`, `cacheScope: "public"`.

- [ ] **Step 1: 실패 테스트 추가**

`test_protocol.py` 끝에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd "C:/Users/user/Desktop/k-apt-alert/mcp-server" && python -m pytest -q`
Expected: 3 failed (`KeyError: 'resultType'` 또는 `'ttlMs'`), 11 passed

- [ ] **Step 3: `_result` 확장**

`server.py` `_result` 교체:

```python
def _result(rid, result: dict):
    # 2026-07-28: 모든 result에 resultType 필수, serverInfo SHOULD.
    # Legacy 클라이언트는 모르는 필드를 무시하므로 공통 적용.
    out = dict(result)
    out.setdefault("resultType", "complete")
    meta = dict(out.get("_meta") or {})
    meta.setdefault(META_SERVER, SERVER_INFO)
    out["_meta"] = meta
    return {"jsonrpc": "2.0", "id": rid, "result": out}
```

- [ ] **Step 4: `tools/list` 분기 교체**

```python
    if method == "tools/list":
        return _result(rid, {"tools": TOOLS, "ttlMs": 3600000, "cacheScope": "public"})
```

- [ ] **Step 5: 통과 확인**

Run: `cd "C:/Users/user/Desktop/k-apt-alert/mcp-server" && python -m pytest -q`
Expected: `14 passed`

- [ ] **Step 6: 실제 Claude Code 핸드셰이크 스모크 (Legacy 경로 수동 확인)**

```bash
cd "C:/Users/user/Desktop/k-apt-alert" && printf '%s\n%s\n%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 | PYTHONIOENCODING=utf-8 python mcp-server/server.py | python -c "import sys,json; [print(json.loads(l)['id'], list(json.loads(l)['result'].keys())) for l in sys.stdin]"
```

Expected 출력 2줄: `1 ['protocolVersion', 'capabilities', 'serverInfo', 'resultType', '_meta']`, `2 ['tools', 'ttlMs', 'cacheScope', 'resultType', '_meta']`

- [ ] **Step 7: 커밋**

```bash
cd "C:/Users/user/Desktop/k-apt-alert" && git add mcp-server && git commit -m "feat(mcp-server): 모든 result에 resultType·serverInfo 첨부, tools/list에 ttlMs·cacheScope 캐시 힌트"
```

---

### Task 4: CI 연결, 버전 범프, README

**Files:**
- Modify: `.github/workflows/test.yml:32-44` (pytest-suite job)
- Modify: `.claude-plugin/plugin.json` (`"version": "1.0.0"`)
- Modify: `mcp-server/server.py` (`SERVER_VERSION = "1.0.0"`, 모듈 docstring)
- Modify: `README.md:293`

**Interfaces:**
- Consumes: Task 1~3 테스트 14개
- Produces: CI에서 `mcp-server` 테스트 실행. 플러그인 버전 `1.1.0`.

- [ ] **Step 1: CI 스텝 추가**

`.github/workflows/test.yml`의 `pytest-suite` job, `Run pytest` 스텝 아래에 추가:

```yaml
      - name: Run mcp-server pytest
        working-directory: mcp-server
        run: python -m pytest -q
```

- [ ] **Step 2: 버전 범프**

```bash
cd "C:/Users/user/Desktop/k-apt-alert" && sed -i 's/SERVER_VERSION = "1.0.0"/SERVER_VERSION = "1.1.0"/' mcp-server/server.py && sed -i 's/"version": "1.0.0"/"version": "1.1.0"/' .claude-plugin/plugin.json && grep -n '1.1.0' mcp-server/server.py .claude-plugin/plugin.json
```

Expected: 두 파일 각 1줄 매치.

- [ ] **Step 3: server.py 모듈 docstring 갱신**

docstring 첫 단락(`Render에 떠 있는 FastAPI 프록시(REST)를 MCP(stdio, JSON-RPC 2.0)로 감싼다.` 줄) 아래에 추가:

```
Dual-era: MCP 2026-07-28(Modern, 요청별 _meta 버전·capabilities, server/discover)과
2025-11-25 이전(Legacy, initialize 핸드셰이크)을 한 프로세스에서 동시에 처리한다.
```

- [ ] **Step 4: README 갱신**

`README.md` 293행을 교체:

```markdown
- [`mcp-server/server.py`](mcp-server/server.py) — 프록시를 MCP(stdio)로 노출하는 의존성 0 서버. 툴 7종 (search_announcements·list_categories·score_profile·get_notice_raw·get_changes·send_notification·get_competition). MCP 스펙 2026-07-28(stateless, `server/discover`)과 기존 `initialize` 핸드셰이크를 모두 지원하는 dual-era 구현. 테스트: `cd mcp-server && python -m pytest -q`
```

(기존 줄의 em dash와 가운뎃점은 원문 포맷 유지. 새로 추가한 문장에만 규칙 적용.)

- [ ] **Step 5: 전체 테스트 재확인**

Run: `cd "C:/Users/user/Desktop/k-apt-alert/mcp-server" && python -m pytest -q && cd ../proxy && python -m pytest -q`
Expected: mcp-server `14 passed`, proxy 기존 전부 passed.

- [ ] **Step 6: 커밋**

```bash
cd "C:/Users/user/Desktop/k-apt-alert" && git add .github/workflows/test.yml .claude-plugin/plugin.json mcp-server/server.py README.md && git commit -m "ci+docs(mcp-server): mcp-server pytest CI 연결, 플러그인 1.1.0, dual-era 설명"
```

---

## Self-Review

- 스펙 커버: `initialize` 제거 대응(Task 2), `server/discover` MUST(Task 2), `_meta` 필수 키와 `-32602`(Task 2), `-32022` + `data.supported`(Task 2), `resultType` 필수(Task 3), `serverInfo` SHOULD(Task 3), `tools/list` `ttlMs`/`cacheScope` + 결정적 순서(Task 3), Legacy 호환(Task 1 회귀 + Task 3 스모크). `ping` 제거는 Modern 클라이언트가 보내지 않으므로 서버 측 조치 불필요, Legacy용으로 유지.
- 범위 밖(의도적): Streamable HTTP 전송, `subscriptions/listen`, MRTR. stdio 툴 전용 서버라 해당 없음.
- 타입 일관성: `_error(rid, code, message, data=None)` 시그니처를 Task 2에서 정의, 기존 3개 호출부는 위치 인자 3개라 호환. `SERVER_INFO`는 Task 2 정의, Task 3 테스트에서 사용. `META_SERVER` 동일.
- 플레이스홀더 없음.
