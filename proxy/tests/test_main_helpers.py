"""main.py 순수 함수 테스트 — 라우트와 분리된 헬퍼들."""

import os

# DATA_GO_KR_API_KEY 누락 시 라우트가 503이지만, 헬퍼 import에는 영향 없음
os.environ.setdefault("DATA_GO_KR_API_KEY", "test-key")

from datetime import datetime, timedelta

import pytest

import main


# ─── _add_d_day ───────────────────────────────────────────────────────


def _today_offset(days: int) -> str:
    """오늘 ± days일을 YYYYMMDD 포맷으로."""
    return (datetime.now().date() + timedelta(days=days)).strftime("%Y%m%d")


def test_add_d_day_future_date():
    ann = {"rcept_end": _today_offset(5)}
    result = main._add_d_day(ann)
    assert result["d_day"] == 5
    assert result["d_day_label"] == "D-5"


def test_add_d_day_today():
    ann = {"rcept_end": _today_offset(0)}
    result = main._add_d_day(ann)
    assert result["d_day"] == 0
    assert "D-Day" in result["d_day_label"]


def test_add_d_day_past_date():
    ann = {"rcept_end": _today_offset(-3)}
    result = main._add_d_day(ann)
    assert result["d_day"] == -3
    assert result["d_day_label"] == "마감"


def test_add_d_day_iso_format_dashes():
    """YYYY-MM-DD 포맷도 처리."""
    target = (datetime.now().date() + timedelta(days=2)).strftime("%Y-%m-%d")
    ann = {"rcept_end": target}
    result = main._add_d_day(ann)
    assert result["d_day"] == 2


def test_add_d_day_missing_field():
    ann = {}
    result = main._add_d_day(ann)
    assert result["d_day"] is None
    assert result["d_day_label"] == ""


def test_add_d_day_invalid_format():
    ann = {"rcept_end": "not-a-date"}
    result = main._add_d_day(ann)
    assert result["d_day"] is None


def test_add_d_day_short_string():
    ann = {"rcept_end": "2026"}  # 8자 미만
    result = main._add_d_day(ann)
    assert result["d_day"] is None


# ─── _is_active ───────────────────────────────────────────────────────


def test_is_active_future():
    assert main._is_active({"rcept_end": _today_offset(1)}) is True


def test_is_active_today():
    assert main._is_active({"rcept_end": _today_offset(0)}) is True  # >= today


def test_is_active_past():
    assert main._is_active({"rcept_end": _today_offset(-1)}) is False


def test_is_active_empty():
    assert main._is_active({}) is False
    assert main._is_active({"rcept_end": ""}) is False


def test_is_active_invalid_format():
    assert main._is_active({"rcept_end": "garbage"}) is False


# ─── _dedup_announcements ─────────────────────────────────────────────


def test_dedup_by_id():
    items = [
        {"id": "x1", "name": "A", "region": "서울", "district": "강남구"},
        {"id": "x1", "name": "A", "region": "서울", "district": "강남구"},
    ]
    result = main._dedup_announcements(items)
    assert len(result) == 1


def test_dedup_by_name_region_district():
    """같은 이름+지역+구라면 다른 ID여도 중복 (예: AP1BL/AP2BL)."""
    items = [
        {"id": "p_001", "name": "OO타운(AP1BL)", "region": "경기", "district": "성남시"},
        {"id": "p_002", "name": "OO타운(AP2BL)", "region": "경기", "district": "성남시"},
    ]
    result = main._dedup_announcements(items)
    assert len(result) == 1


def test_dedup_keeps_distinct_districts():
    items = [
        {"id": "1", "name": "X", "region": "서울", "district": "강남구"},
        {"id": "2", "name": "X", "region": "서울", "district": "서초구"},
    ]
    assert len(main._dedup_announcements(items)) == 2


def test_dedup_keeps_distinct_names():
    items = [
        {"id": "1", "name": "A", "region": "서울", "district": "강남구"},
        {"id": "2", "name": "B", "region": "서울", "district": "강남구"},
    ]
    assert len(main._dedup_announcements(items)) == 2


def test_dedup_empty_name_falls_through():
    """name이 빈 문자열이면 name+region+district 키 dedup 적용 안 함."""
    items = [
        {"id": "1", "name": "", "region": "서울", "district": "강남구"},
        {"id": "2", "name": "", "region": "서울", "district": "강남구"},
    ]
    assert len(main._dedup_announcements(items)) == 2


def test_dedup_strips_paren_suffix():
    """이름의 (서브타입) 부분은 dedup 키에서 제거."""
    items = [
        {"id": "1", "name": "센트럴파크(전용84)", "region": "서울", "district": "송파구"},
        {"id": "2", "name": "센트럴파크(전용74)", "region": "서울", "district": "송파구"},
    ]
    assert len(main._dedup_announcements(items)) == 1


# ─── _apply_extra_filters ─────────────────────────────────────────────


def _ann(**kw):
    base = {"id": "x", "total_units": "100", "constructor": "현대건설"}
    base.update(kw)
    return base


def test_filter_min_units_passes():
    anns = [_ann(total_units="500")]
    assert len(main._apply_extra_filters(anns, 100, "", "")) == 1


def test_filter_min_units_blocks():
    anns = [_ann(total_units="50")]
    assert len(main._apply_extra_filters(anns, 100, "", "")) == 0


def test_filter_min_units_handles_comma_separated():
    anns = [_ann(total_units="1,500")]
    assert len(main._apply_extra_filters(anns, 1000, "", "")) == 1


def test_filter_min_units_invalid_string_treated_as_zero():
    anns = [_ann(total_units="알수없음")]
    assert len(main._apply_extra_filters(anns, 100, "", "")) == 0


def test_filter_constructor_match_case_insensitive():
    anns = [_ann(constructor="삼성물산(주)")]
    assert len(main._apply_extra_filters(anns, 0, "삼성", "")) == 1


def test_filter_constructor_partial_match():
    anns = [_ann(constructor="현대건설")]
    assert len(main._apply_extra_filters(anns, 0, "현대,GS", "")) == 1


def test_filter_constructor_no_match():
    anns = [_ann(constructor="중소건설")]
    assert len(main._apply_extra_filters(anns, 0, "삼성,현대,GS", "")) == 0


def test_filter_exclude_ids():
    anns = [_ann(id="a"), _ann(id="b"), _ann(id="c")]
    result = main._apply_extra_filters(anns, 0, "", "a,c")
    assert {a["id"] for a in result} == {"b"}


def test_filter_exclude_ids_empty_string_no_op():
    anns = [_ann(id="a")]
    assert len(main._apply_extra_filters(anns, 0, "", "")) == 1


def test_filter_combined_all_axes():
    anns = [
        _ann(id="big-삼성", total_units="500", constructor="삼성물산"),
        _ann(id="small-삼성", total_units="50", constructor="삼성물산"),
        _ann(id="big-중소", total_units="500", constructor="중소건설"),
        _ann(id="excluded", total_units="500", constructor="삼성물산"),
    ]
    result = main._apply_extra_filters(anns, min_units=200, constructor_contains="삼성", exclude_ids="excluded")
    assert {a["id"] for a in result} == {"big-삼성"}


# ─── _apply_reminder_filter ───────────────────────────────────────────


def test_reminder_empty_passes_through():
    anns = [{"d_day": 5}, {"d_day": -1}]
    assert main._apply_reminder_filter(anns, "") == anns


def test_reminder_d3_includes_today_to_d3():
    anns = [{"d_day": d} for d in [-1, 0, 1, 2, 3, 4, 5]]
    result = main._apply_reminder_filter(anns, "d3")
    assert {a["d_day"] for a in result} == {0, 1, 2, 3}


def test_reminder_d1_only_today_and_tomorrow():
    anns = [{"d_day": d} for d in [-1, 0, 1, 2]]
    result = main._apply_reminder_filter(anns, "d1")
    assert {a["d_day"] for a in result} == {0, 1}


def test_reminder_winners_7_to_10_days_after_close():
    anns = [{"d_day": d} for d in [-6, -7, -8, -10, -11, -15]]
    result = main._apply_reminder_filter(anns, "winners")
    assert {a["d_day"] for a in result} == {-7, -8, -10}


def test_reminder_contract_14_to_21_days_after_close():
    anns = [{"d_day": d} for d in [-13, -14, -18, -21, -22]]
    result = main._apply_reminder_filter(anns, "contract")
    assert {a["d_day"] for a in result} == {-14, -18, -21}


def test_reminder_skips_d_day_none():
    anns = [{"d_day": None}, {"d_day": 1}]
    result = main._apply_reminder_filter(anns, "d1")
    assert result == [{"d_day": 1}]


def test_reminder_unknown_type_returns_empty():
    anns = [{"d_day": 1}]
    result = main._apply_reminder_filter(anns, "unknown")
    assert result == []


# ─── _ttl_for ─────────────────────────────────────────────────────────


def test_ttl_for_known_prefix_apt():
    assert main._ttl_for("apt:2") == main.CACHE_TTLS["apt"]


def test_ttl_for_known_prefix_sh():
    assert main._ttl_for("sh:3") == main.CACHE_TTLS["sh"]


def test_ttl_for_unknown_prefix_falls_back_to_default():
    assert main._ttl_for("unknown:1") == main.CACHE_TTL_SECONDS


def test_ttl_for_no_colon():
    assert main._ttl_for("apt") == main.CACHE_TTLS["apt"]


# ─── _check_rate_limit ────────────────────────────────────────────────


def test_check_rate_limit_increments():
    main._rate_counter["date"] = ""
    main._rate_counter["count"] = 0
    c1, limit = main._check_rate_limit()
    c2, _ = main._check_rate_limit()
    assert c1 == 1 and c2 == 2
    assert limit == main.DAILY_CALL_LIMIT


def test_check_rate_limit_resets_on_new_day():
    main._rate_counter["date"] = "1900-01-01"
    main._rate_counter["count"] = 9999
    c, _ = main._check_rate_limit()
    assert c == 1  # 오늘 첫 호출로 리셋됨


# ─── _notice_raw_check_limit ──────────────────────────────────────────


def test_notice_raw_check_limit_separate_counter():
    main._notice_raw_counter["date"] = ""
    main._notice_raw_counter["count"] = 0
    c1, limit = main._notice_raw_check_limit()
    c2, _ = main._notice_raw_check_limit()
    assert c1 == 1 and c2 == 2
    assert limit == main.NOTICE_RAW_DAILY_LIMIT_FREE


# ─── _resolve_url_from_cache ──────────────────────────────────────────


def test_resolve_url_from_cache_hit():
    main._cache.clear()
    main._cache["apt:2"] = {
        "ts": 0,
        "items": [
            {"id": "apt_001", "url": "https://www.applyhome.co.kr/x"},
            {"id": "apt_002", "url": "https://www.applyhome.co.kr/y"},
        ],
    }
    assert main._resolve_url_from_cache("apt_002") == "https://www.applyhome.co.kr/y"


def test_resolve_url_from_cache_miss():
    main._cache.clear()
    assert main._resolve_url_from_cache("apt_nope") is None


def test_resolve_url_from_cache_searches_all_categories():
    main._cache.clear()
    main._cache["apt:2"] = {"ts": 0, "items": [{"id": "apt_001", "url": "u1"}]}
    main._cache["lh:2"] = {"ts": 0, "items": [{"id": "lh_001", "url": "u2"}]}
    assert main._resolve_url_from_cache("lh_001") == "u2"


# ─── _resolve_tier (Phase 1 stub) ─────────────────────────────────────


def test_resolve_tier_always_free_phase1():
    """Phase 1은 인증 토큰 무관하게 free 강제."""
    assert main._resolve_tier(None) == "free"
    assert main._resolve_tier("Bearer fake") == "free"
    assert main._resolve_tier("") == "free"


# ─── 메시지 빌더 (Slack/Telegram) ─────────────────────────────────────


def _ann_for_msg(**kw):
    base = {
        "name": "테스트 단지",
        "region": "서울",
        "district": "강남구",
        "period": "2026-05-01 ~ 2026-05-05",
        "d_day": 3,
        "d_day_label": "D-3",
        "total_units": "350",
        "house_category": "APT",
        "url": "https://www.applyhome.co.kr/test",
    }
    base.update(kw)
    return base


def test_build_slack_blocks_basic():
    payload = main._build_slack_blocks([_ann_for_msg()])
    assert "blocks" in payload
    blocks = payload["blocks"]
    assert blocks[0]["type"] == "header"
    assert "1건" in blocks[0]["text"]["text"]
    section = next(b for b in blocks if b["type"] == "section")
    assert "테스트 단지" in section["text"]["text"]


def test_build_slack_blocks_urgency_d1_red():
    payload = main._build_slack_blocks([_ann_for_msg(d_day=1)])
    section = next(b for b in payload["blocks"] if b["type"] == "section")
    assert "🔴" in section["text"]["text"]


def test_build_slack_blocks_urgency_d3_yellow():
    payload = main._build_slack_blocks([_ann_for_msg(d_day=3)])
    section = next(b for b in payload["blocks"] if b["type"] == "section")
    assert "🟡" in section["text"]["text"]


def test_build_slack_blocks_urgency_d5_green():
    payload = main._build_slack_blocks([_ann_for_msg(d_day=5)])
    section = next(b for b in payload["blocks"] if b["type"] == "section")
    assert "🟢" in section["text"]["text"]


def test_build_slack_blocks_truncates_at_10():
    """10건 초과면 '외 N건 더' 추가, 본문은 10개만."""
    anns = [_ann_for_msg(name=f"단지{i}") for i in range(15)]
    payload = main._build_slack_blocks(anns)
    sections = [b for b in payload["blocks"] if b["type"] == "section"]
    assert len(sections) == 11
    assert "외 5건 더" in sections[-1]["text"]["text"]


def test_build_telegram_text_basic():
    text = main._build_telegram_text([_ann_for_msg()])
    assert "테스트 단지" in text
    assert "<b>" in text
    assert "강남구" in text


def test_build_telegram_text_truncates_at_10():
    anns = [_ann_for_msg(name=f"단지{i}") for i in range(12)]
    text = main._build_telegram_text(anns)
    assert "외 2건 더" in text
    assert "단지0" in text and "단지9" in text


def test_build_telegram_text_escapes_safely():
    text = main._build_telegram_text([_ann_for_msg(url="https://example.com/path")])
    assert 'href="https://example.com/path"' in text


def test_build_messages_handle_missing_fields():
    """필드 누락된 공고도 ?로 fallback해서 죽지 않음."""
    bad = {"d_day": 5}
    main._build_slack_blocks([bad])
    main._build_telegram_text([bad])
