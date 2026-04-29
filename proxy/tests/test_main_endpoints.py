"""FastAPI 엔드포인트 통합 테스트 — TestClient + 외부 의존성 mocking."""

import os
from unittest import mock

# DATA_GO_KR_API_KEY 라우트 가드 통과용
os.environ.setdefault("DATA_GO_KR_API_KEY", "test-key")

import pytest
from fastapi.testclient import TestClient

import main
from crawlers import notice_raw

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def reset_state():
    """각 테스트 전후 캐시·카운터·notice_raw 캐시 모두 초기화."""
    main._cache.clear()
    main._rate_counter.update({"date": "", "count": 0})
    main._notice_raw_counter.update({"date": "", "count": 0})
    notice_raw._cache.clear()
    yield
    main._cache.clear()
    notice_raw._cache.clear()


# ─── /health ──────────────────────────────────────────────────────────


def test_health_returns_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "api_key_configured" in body


# ─── /v1/apt/categories ──────────────────────────────────────────────


def test_categories_lists_eight():
    resp = client.get("/v1/apt/categories")
    assert resp.status_code == 200
    body = resp.json()
    ids = {c["id"] for c in body["categories"]}
    assert ids == {"apt", "officetell", "lh", "remndr", "pbl_pvt_rent", "opt", "sh", "gh"}


def test_categories_have_required_fields():
    resp = client.get("/v1/apt/categories")
    for cat in resp.json()["categories"]:
        assert "id" in cat and "name" in cat and "description" in cat


# ─── /v1/apt/cache ───────────────────────────────────────────────────


def test_cache_status_empty_initial():
    resp = client.get("/v1/apt/cache")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entries"] == []
    assert "rate_limit" in body
    assert body["ttl_seconds"] == main.CACHE_TTL_SECONDS


def test_cache_status_reflects_entries():
    main._cache["apt:2"] = {"ts": 0, "items": [{"id": "x"}, {"id": "y"}]}
    resp = client.get("/v1/apt/cache")
    body = resp.json()
    keys = [e["key"] for e in body["entries"]]
    assert "apt:2" in keys


# ─── /v1/apt/announcements ───────────────────────────────────────────


def _make_ann(**kw):
    base = {
        "id": "apt_001",
        "name": "테스트단지",
        "region": "서울",
        "district": "강남구",
        "address": "서울특별시 강남구 ...",
        "period": "2026-05-01 ~ 2026-05-10",
        "rcept_end": "20260510",
        "total_units": "300",
        "house_type": "민영",
        "constructor": "삼성물산",
        "url": "https://www.applyhome.co.kr/test",
        "speculative_zone": "Y",
        "price_controlled": "N",
        "house_category": "APT",
    }
    base.update(kw)
    return base


def test_announcements_no_api_key_raises_503(monkeypatch):
    monkeypatch.setattr(main, "DATA_GO_KR_API_KEY", "")
    resp = client.get("/v1/apt/announcements?category=apt")
    assert resp.status_code == 503


def test_announcements_invalid_category_raises_400():
    resp = client.get("/v1/apt/announcements?category=bogus")
    assert resp.status_code == 400


def test_announcements_returns_filtered_list(monkeypatch):
    """_fetch_and_filter를 mocking — 라우트 통합 흐름만 검증."""
    monkeypatch.setattr(
        main,
        "_fetch_and_filter",
        lambda *args, **kw: ([_make_ann()], None, None),
    )
    resp = client.get("/v1/apt/announcements?category=apt&active_only=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["announcements"][0]["id"] == "apt_001"
    assert body["filters"]["category"] == "apt"


def test_announcements_apply_extra_filters(monkeypatch):
    anns = [
        _make_ann(id="big", total_units="500"),
        _make_ann(id="small", total_units="50"),
    ]
    monkeypatch.setattr(main, "_fetch_and_filter", lambda *args, **kw: (anns, None, None))
    resp = client.get("/v1/apt/announcements?category=apt&min_units=200")
    body = resp.json()
    assert body["count"] == 1
    assert body["announcements"][0]["id"] == "big"


def test_announcements_reminder_filter(monkeypatch):
    a1 = _make_ann(id="urgent")
    a2 = _make_ann(id="far")
    a1["d_day"] = 1
    a2["d_day"] = 10
    monkeypatch.setattr(main, "_fetch_and_filter", lambda *args, **kw: ([a1, a2], None, None))
    resp = client.get("/v1/apt/announcements?reminder=d1")
    body = resp.json()
    ids = [a["id"] for a in body["announcements"]]
    assert ids == ["urgent"]


def test_announcements_invalid_months_back_422():
    resp = client.get("/v1/apt/announcements?months_back=0")
    assert resp.status_code == 422  # ge=1 violation


def test_announcements_filters_echo(monkeypatch):
    monkeypatch.setattr(main, "_fetch_and_filter", lambda *args, **kw: ([], None, None))
    resp = client.get(
        "/v1/apt/announcements?category=apt&region=서울,경기&exclude_ids=a,b"
    )
    body = resp.json()
    f = body["filters"]
    assert f["category"] == "apt"
    assert set(f["region"]) == {"서울", "경기"}
    assert set(f["exclude_ids"]) == {"a", "b"}


# ─── /v1/apt/notify ──────────────────────────────────────────────────


def test_notify_requires_channel():
    resp = client.post("/v1/apt/notify")
    assert resp.status_code == 400


def test_notify_telegram_token_without_chat_id_400():
    resp = client.post("/v1/apt/notify?telegram_token=t")
    assert resp.status_code == 400


def test_notify_no_active_announcements_returns_zero(monkeypatch):
    monkeypatch.setattr(main, "_fetch_and_filter", lambda *args, **kw: ([], None, None))
    resp = client.post("/v1/apt/notify?webhook_url=https://hooks.slack.com/x")
    assert resp.status_code == 200
    assert resp.json()["sent"] == 0


def test_notify_slack_success(monkeypatch):
    a = _make_ann()
    a["d_day"] = 3
    monkeypatch.setattr(main, "_fetch_and_filter", lambda *args, **kw: ([a], None, None))
    sent_calls = []

    def fake_send(url, anns):
        sent_calls.append((url, len(anns)))

    monkeypatch.setattr(main, "_send_slack", fake_send)
    resp = client.post("/v1/apt/notify?webhook_url=https://hooks.slack.com/x")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] == 1
    assert "slack" in body["channels"]
    assert sent_calls and sent_calls[0][1] == 1


def test_notify_telegram_success(monkeypatch):
    a = _make_ann()
    a["d_day"] = 3
    monkeypatch.setattr(main, "_fetch_and_filter", lambda *args, **kw: ([a], None, None))
    monkeypatch.setattr(main, "_send_telegram", lambda *args, **kw: None)
    resp = client.post("/v1/apt/notify?telegram_token=t&telegram_chat_id=c")
    body = resp.json()
    assert body["sent"] == 1
    assert "telegram" in body["channels"]


def test_notify_dual_channel(monkeypatch):
    a = _make_ann()
    a["d_day"] = 3
    monkeypatch.setattr(main, "_fetch_and_filter", lambda *args, **kw: ([a], None, None))
    monkeypatch.setattr(main, "_send_slack", lambda *args, **kw: None)
    monkeypatch.setattr(main, "_send_telegram", lambda *args, **kw: None)
    resp = client.post(
        "/v1/apt/notify?webhook_url=https://hooks.slack.com/x"
        "&telegram_token=t&telegram_chat_id=c"
    )
    assert set(resp.json()["channels"]) == {"slack", "telegram"}


def test_notify_partial_failure_one_channel_succeeds(monkeypatch):
    from fastapi import HTTPException

    a = _make_ann()
    a["d_day"] = 3
    monkeypatch.setattr(main, "_fetch_and_filter", lambda *args, **kw: ([a], None, None))

    def slack_fail(*a, **kw):
        raise HTTPException(status_code=502, detail="Slack down")

    monkeypatch.setattr(main, "_send_slack", slack_fail)
    monkeypatch.setattr(main, "_send_telegram", lambda *args, **kw: None)
    resp = client.post(
        "/v1/apt/notify?webhook_url=https://hooks.slack.com/x"
        "&telegram_token=t&telegram_chat_id=c"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["channels"] == ["telegram"]
    assert "slack" in body["errors"]


def test_notify_all_channels_fail_502(monkeypatch):
    from fastapi import HTTPException

    a = _make_ann()
    a["d_day"] = 3
    monkeypatch.setattr(main, "_fetch_and_filter", lambda *args, **kw: ([a], None, None))
    monkeypatch.setattr(
        main,
        "_send_slack",
        lambda *args, **kw: (_ for _ in ()).throw(HTTPException(502, "down")),
    )
    monkeypatch.setattr(
        main,
        "_send_telegram",
        lambda *args, **kw: (_ for _ in ()).throw(HTTPException(502, "down")),
    )
    resp = client.post(
        "/v1/apt/notify?webhook_url=https://hooks.slack.com/x"
        "&telegram_token=t&telegram_chat_id=c"
    )
    assert resp.status_code == 502


# ─── /v1/apt/notice/{id}/raw ─────────────────────────────────────────


def _fake_resp(html: str, status: int = 200):
    resp = mock.Mock()
    resp.text = html
    resp.status_code = status
    resp.raise_for_status = mock.Mock()
    if status >= 400:
        from requests import HTTPError

        resp.raise_for_status.side_effect = HTTPError(f"{status}")
    return resp


_SAMPLE_HTML = """
<!doctype html><html><head><title>테스트 공고</title></head>
<body><div id="pblancCont">
<h2>신청자격</h2><p>무주택세대구성원</p>
<h2>공급일정</h2><p>2026-05-01</p>
</div></body></html>
"""


def test_notice_raw_via_url_fallback():
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_resp(_SAMPLE_HTML)):
        resp = client.get(
            "/v1/apt/notice/apt_zzz/raw",
            params={"url": "https://www.applyhome.co.kr/x"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "apt_zzz"
    assert body["title"] == "테스트 공고"
    assert "무주택세대구성원" in body["text"]
    assert body["tier"] == "free"
    assert body["effective_max_chars"] == 30000


def test_notice_raw_via_id_cache_lookup():
    main._cache["apt:2"] = {
        "ts": 0,
        "items": [
            {"id": "apt_cached", "url": "https://www.applyhome.co.kr/cached"}
        ],
    }
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_resp(_SAMPLE_HTML)):
        resp = client.get("/v1/apt/notice/apt_cached/raw")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://www.applyhome.co.kr/cached"


def test_notice_raw_404_when_id_unknown_and_no_url():
    resp = client.get("/v1/apt/notice/missing/raw")
    assert resp.status_code == 404
    assert "not in" in resp.json()["detail"]


def test_notice_raw_unsupported_host_400():
    resp = client.get(
        "/v1/apt/notice/x/raw",
        params={"url": "https://evil.example.com/abc"},
    )
    assert resp.status_code == 400
    assert "unsupported host" in resp.json()["detail"]


def test_notice_raw_extract_failure_502():
    from requests import RequestException

    with mock.patch.object(notice_raw.requests, "get", side_effect=RequestException("boom")):
        resp = client.get(
            "/v1/apt/notice/apt_x/raw",
            params={"url": "https://www.applyhome.co.kr/x"},
        )
    assert resp.status_code == 502
    assert "extract failed" in resp.json()["detail"]


def test_notice_raw_max_chars_clamped_to_free_tier():
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_resp(_SAMPLE_HTML)):
        resp = client.get(
            "/v1/apt/notice/apt_clamp/raw",
            params={"url": "https://www.applyhome.co.kr/x", "max_chars": 80000},
        )
    body = resp.json()
    assert body["effective_max_chars"] == 30000
    assert body["tier_capped"] is True


def test_notice_raw_paid_tier_downgraded_when_no_auth():
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_resp(_SAMPLE_HTML)):
        resp = client.get(
            "/v1/apt/notice/apt_p/raw",
            params={"url": "https://www.applyhome.co.kr/x", "tier": "paid"},
        )
    assert resp.json()["tier"] == "free"


def test_notice_raw_max_chars_below_minimum_422():
    resp = client.get(
        "/v1/apt/notice/apt_x/raw",
        params={"url": "https://www.applyhome.co.kr/x", "max_chars": 100},
    )
    assert resp.status_code == 422


def test_notice_raw_force_refresh_invalidates_cache():
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_resp(_SAMPLE_HTML)) as mocked:
        client.get(
            "/v1/apt/notice/apt_fr/raw",
            params={"url": "https://www.applyhome.co.kr/x"},
        )
        client.get(
            "/v1/apt/notice/apt_fr/raw",
            params={"url": "https://www.applyhome.co.kr/x", "force_refresh": "true"},
        )
        assert mocked.call_count == 2


def test_notice_raw_rate_limit_429(monkeypatch):
    monkeypatch.setattr(main, "NOTICE_RAW_DAILY_LIMIT_FREE", 1)
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_resp(_SAMPLE_HTML)):
        r1 = client.get(
            "/v1/apt/notice/apt_rl1/raw",
            params={"url": "https://www.applyhome.co.kr/x"},
        )
        r2 = client.get(
            "/v1/apt/notice/apt_rl2/raw",
            params={"url": "https://www.applyhome.co.kr/y"},
        )
    assert r1.status_code == 200
    assert r2.status_code == 429


# ─── /v1/apt/notice/cache-status ─────────────────────────────────────


def test_notice_cache_status_returns_structure():
    resp = client.get("/v1/apt/notice/cache-status")
    assert resp.status_code == 200
    body = resp.json()
    assert "cache" in body and "rate_limit" in body and "tier_limits" in body
    assert body["tier_limits"] == {"free": 30000, "paid": 80000}
