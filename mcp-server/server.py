#!/usr/bin/env python3
"""k-apt-alert MCP 서버 — 의존성 0개 (Python 표준 라이브러리만).

Render에 떠 있는 FastAPI 프록시(REST)를 MCP(stdio, JSON-RPC 2.0)로 감싼다.
Dual-era: MCP 2026-07-28(Modern, 요청별 _meta 버전·capabilities, server/discover)과
2025-11-25 이전(Legacy, initialize 핸드셰이크)을 한 프로세스에서 동시에 처리한다.
Claude Code 플러그인이 .mcp.json으로 이 서버를 stdio 기동한다.

왜 SDK(pip install mcp) 안 쓰고 stdlib만? — 어떤 Python 3.8+ 환경에서도
설치 마찰 0으로 즉시 동작. MCP stdio 전송은 "줄바꿈 구분 JSON-RPC"라
표준 라이브러리만으로 정확히 구현 가능하다.

엔드포인트 매핑 (proxy/main.py 기준, 추측 아님):
  GET  /v1/apt/announcements          → search_announcements
  GET  /v1/apt/categories             → list_categories
  POST /v1/apt/score                  → score_profile
  GET  /v1/apt/notice/{id}/raw        → get_notice_raw
  GET  /v1/apt/changes                → get_changes
  POST /v1/apt/notify                 → send_notification
  GET  /v1/apt/announcements/{id}/competition → get_competition
"""

# PEP 604(`dict | None`) 어노테이션을 문자열로 지연 평가 → Python 3.7~3.9에서도
# import 단계 TypeError 없이 동작 (의존성 0 + 어떤 Python에서도 동작 보장).
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PROXY = os.environ.get("KAPT_PROXY_URL", "https://k-apt-alert-proxy.onrender.com").rstrip("/")
TIMEOUT = int(os.environ.get("KAPT_TIMEOUT", "180"))
SERVER_NAME = "k-apt-alert"
SERVER_VERSION = "1.1.0"
DEFAULT_PROTOCOL = "2025-06-18"
UA = f"{SERVER_NAME}-mcp/{SERVER_VERSION}"

# ── MCP 2026-07-28 (Modern, stateless) ──
# Modern 클라이언트는 initialize 대신 요청마다 _meta에 버전·capabilities를 싣는다.
# Legacy(initialize 핸드셰이크) 경로는 그대로 유지 → dual-era 서버.
MODERN_VERSIONS = ["2026-07-28"]
META_VER = "io.modelcontextprotocol/protocolVersion"
META_CAPS = "io.modelcontextprotocol/clientCapabilities"
META_SERVER = "io.modelcontextprotocol/serverInfo"
SERVER_INFO = {"name": SERVER_NAME, "version": SERVER_VERSION}


# ─────────────────────────────────────────────────────────────
# HTTP 헬퍼 (urllib — 외부 의존성 없음)
# ─────────────────────────────────────────────────────────────
def _qs(params: dict | None) -> str:
    if not params:
        return ""
    clean = {}
    for k, v in params.items():
        if v in (None, "", []):
            continue
        clean[k] = "true" if v is True else "false" if v is False else v
    return ("?" + urllib.parse.urlencode(clean)) if clean else ""


def _http_get(path: str, params: dict | None = None) -> dict:
    url = f"{PROXY}{path}{_qs(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_post(path: str, body: dict, params: dict | None = None) -> dict:
    url = f"{PROXY}{path}{_qs(params)}"
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


# ─────────────────────────────────────────────────────────────
# 툴 정의 (inputSchema = JSON Schema)
# ─────────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "search_announcements",
        "description": (
            "한국 청약 공고를 통합 조회한다. 8개 카테고리(apt·officetell·lh·remndr·"
            "pbl_pvt_rent·opt·sh·gh) + 'all'. 지역·세대수·시공사·D-day 필터 지원. "
            "각 공고에 d_day, d_day_label, url 포함."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "default": "all",
                             "description": "apt/officetell/lh/remndr/pbl_pvt_rent/opt/sh/gh/all"},
                "region": {"type": "string", "description": "지역 필터 (쉼표 구분, 예: 서울,경기)"},
                "district": {"type": "string", "description": "구/군 필터 (쉼표 구분)"},
                "active_only": {"type": "boolean", "default": True, "description": "접수 마감 전만"},
                "months_back": {"type": "integer", "default": 2, "minimum": 1, "maximum": 12},
                "min_units": {"type": "integer", "default": 0, "description": "최소 세대수"},
                "constructor_contains": {"type": "string", "description": "시공사 키워드 (쉼표 구분)"},
                "reminder": {"type": "string", "description": "d3/d1/winners/contract"},
            },
        },
    },
    {
        "name": "list_categories",
        "description": "조회 가능한 청약 카테고리 8종 목록과 설명을 반환한다.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "score_profile",
        "description": (
            "결정론적 청약 가점(84점 만점) + 특별공급 자격을 계산한다. 통장 가점 공식·"
            "미성년 인정 한도를 정확히 적용. announcements를 함께 넘기면 공고별 1순위 "
            "자격(priority_checks)도 반환. 프로필은 서버에 저장되지 않는다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {
                    "type": "object",
                    "description": "no_house_years, dependents, subscription_account{years,deposit_count,minor_years_post_2024}, no_house, ever_owned_house, previous_win, marriage_date, children, age 등",
                },
                "specials": {
                    "type": "array", "items": {"type": "string"},
                    "description": "판정할 특별공급 (기본: 신혼부부·생애최초·다자녀·노부모부양·청년)",
                },
                "announcements": {
                    "type": "array", "items": {"type": "object"},
                    "description": "[{id, speculative_zone, region}] — 공고별 1순위 판정용 (선택)",
                },
            },
            "required": ["profile"],
        },
    },
    {
        "name": "get_notice_raw",
        "description": (
            "모집공고 원문 텍스트를 추출한다 (청약홈 PDF·LH·SH 멀티첨부·GH HWP 자동 해석). "
            "자격·일정·금액·유의사항이 text/sections에 포함. 캐시 miss 시 url 직접 전달."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "notice_id": {"type": "string", "description": "공고 ID (예: 2026000116, gh_64782)"},
                "url": {"type": "string", "description": "캐시 miss 시 폴백 URL (applyhome/lh/sh/gh)"},
                "force_refresh": {"type": "boolean", "default": False},
            },
            "required": ["notice_id"],
        },
    },
    {
        "name": "get_changes",
        "description": "공고 변동 이력 조회 (어제 대비 신규·분양가 변경·마감). GitHub Actions가 매일 KST 08:00 갱신.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "이 날짜 이후만 (YYYY-MM-DD)"},
                "change_type": {"type": "string", "description": "new/updated/removed"},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
        },
    },
    {
        "name": "send_notification",
        "description": (
            "조회된 공고를 Slack/Telegram으로 발송한다. webhook_url(Slack) 또는 "
            "telegram_token+telegram_chat_id 필요. 서버 측 7일 중복 방지 기본 적용. "
            "주의: 실제 발송이므로 사용자 확인 후 호출할 것."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "webhook_url": {"type": "string", "description": "Slack Webhook URL"},
                "telegram_token": {"type": "string"},
                "telegram_chat_id": {"type": "string"},
                "category": {"type": "string", "default": "all"},
                "region": {"type": "string"},
                "district": {"type": "string"},
                "min_units": {"type": "integer", "default": 0},
                "reminder": {"type": "string", "description": "d3/d1/winners/contract"},
                "active_only": {"type": "boolean", "default": True},
                "months_back": {"type": "integer", "default": 2},
            },
        },
    },
    {
        "name": "get_competition",
        "description": "공고 경쟁률·커트라인 조회 (3단 폴백: 청약홈 실제 결과 → 지역 12개월 평균 → 통계 추정). 먼저 search_announcements로 캐시에 올라와 있어야 함.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "notice_id": {"type": "string", "description": "공고 ID"},
                "history": {"type": "boolean", "default": False, "description": "지역 과거 이력 활용"},
            },
            "required": ["notice_id"],
        },
    },
]


# ─────────────────────────────────────────────────────────────
# 툴 핸들러
# ─────────────────────────────────────────────────────────────
def _h_search(a):
    return _http_get("/v1/apt/announcements", {
        "category": a.get("category", "all"),
        "region": a.get("region", ""),
        "district": a.get("district", ""),
        "active_only": a.get("active_only", True),
        "months_back": a.get("months_back", 2),
        "min_units": a.get("min_units", 0),
        "constructor_contains": a.get("constructor_contains", ""),
        "reminder": a.get("reminder", ""),
    })


def _h_categories(a):
    return _http_get("/v1/apt/categories")


def _h_score(a):
    body = {"profile": a.get("profile", {})}
    if a.get("specials"):
        body["specials"] = a["specials"]
    if a.get("announcements"):
        body["announcements"] = a["announcements"]
    return _http_post("/v1/apt/score", body)


def _h_notice_raw(a):
    nid = a["notice_id"]
    return _http_get(f"/v1/apt/notice/{urllib.parse.quote(str(nid))}/raw", {
        "url": a.get("url", ""),
        "force_refresh": a.get("force_refresh", False),
    })


def _h_changes(a):
    return _http_get("/v1/apt/changes", {
        "since": a.get("since", ""),
        "change_type": a.get("change_type", ""),
        "limit": a.get("limit", 50),
    })


def _h_notify(a):
    return _http_post("/v1/apt/notify", {}, {
        "webhook_url": a.get("webhook_url", ""),
        "telegram_token": a.get("telegram_token", ""),
        "telegram_chat_id": a.get("telegram_chat_id", ""),
        "category": a.get("category", "all"),
        "region": a.get("region", ""),
        "district": a.get("district", ""),
        "min_units": a.get("min_units", 0),
        "reminder": a.get("reminder", ""),
        "active_only": a.get("active_only", True),
        "months_back": a.get("months_back", 2),
    })


def _h_competition(a):
    nid = a["notice_id"]
    return _http_get(f"/v1/apt/announcements/{urllib.parse.quote(str(nid))}/competition", {
        "history": a.get("history", False),
    })


HANDLERS = {
    "search_announcements": _h_search,
    "list_categories": _h_categories,
    "score_profile": _h_score,
    "get_notice_raw": _h_notice_raw,
    "get_changes": _h_changes,
    "send_notification": _h_notify,
    "get_competition": _h_competition,
}


# ─────────────────────────────────────────────────────────────
# JSON-RPC 디스패치
# ─────────────────────────────────────────────────────────────
def _result(rid, result: dict):
    # 2026-07-28: 모든 result에 resultType 필수, serverInfo SHOULD.
    # Legacy 클라이언트는 모르는 필드를 무시하므로 공통 적용.
    out = dict(result)
    out.setdefault("resultType", "complete")
    meta = dict(out.get("_meta") or {})
    meta.setdefault(META_SERVER, SERVER_INFO)
    out["_meta"] = meta
    return {"jsonrpc": "2.0", "id": rid, "result": out}


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


def _tool_text(obj) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=2)}]}


def handle(msg: dict):
    """JSON-RPC 메시지 처리. notification(id 없음)이면 None 반환(무응답)."""
    method = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {}

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

    if method == "initialize":
        proto = params.get("protocolVersion", DEFAULT_PROTOCOL)
        return _result(rid, {
            "protocolVersion": proto,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # notification — 무응답

    if method == "ping":
        return _result(rid, {})

    if method == "tools/list":
        return _result(rid, {"tools": TOOLS, "ttlMs": 3600000, "cacheScope": "public"})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if not fn:
            return _error(rid, -32602, f"Unknown tool: {name}")
        try:
            return _result(rid, _tool_text(fn(args)))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:500]
            except Exception:
                pass
            return _result(rid, {
                "content": [{"type": "text", "text": f"프록시 HTTP {e.code}: {detail}"}],
                "isError": True,
            })
        except urllib.error.URLError as e:
            # 타임아웃·DNS·연결거부 — Render free tier cold start가 흔한 원인.
            return _result(rid, {
                "content": [{"type": "text", "text": (
                    f"프록시 응답 없음 ({e.reason}). Render free tier가 슬립 중일 수 "
                    "있습니다 — 15~30초 후 한 번 재시도하세요."
                )}],
                "isError": True,
            })
        except Exception as e:  # noqa: BLE001
            return _result(rid, {
                "content": [{"type": "text", "text": f"호출 실패: {type(e).__name__} — {e}"}],
                "isError": True,
            })

    if rid is not None:
        return _error(rid, -32601, f"Method not found: {method}")
    return None  # 알 수 없는 notification


def main():
    # MCP stdio는 UTF-8 JSON-RPC. Windows 기본 stdout(cp949)에서 한글이 깨지므로
    # stdin/stdout을 UTF-8로 강제 (Python 3.7+ reconfigure).
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    # MCP stdio = 줄바꿈 구분 JSON-RPC. 한 줄에 한 메시지.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle(msg)
        except Exception as e:  # noqa: BLE001
            rid = msg.get("id") if isinstance(msg, dict) else None
            resp = _error(rid, -32603, f"Internal error: {type(e).__name__}") if rid is not None else None
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
