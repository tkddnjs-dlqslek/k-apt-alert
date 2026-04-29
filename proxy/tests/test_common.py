"""crawlers/common.py — 주소 파싱·정규화·HTTP 재시도 테스트."""

from unittest import mock

import pytest
import requests

from crawlers import common
from crawlers.common import (
    AREA_CODE_MAP,
    extract_district,
    fetch_all_pages,
    fetch_page,
    fetch_size_map,
    normalize_applyhome,
)


# ─── extract_district ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "address,expected",
    [
        ("서울특별시 서초구 서초대로 123", "서초구"),
        ("서울특별시 강남구 테헤란로", "강남구"),
        ("경기도 성남시 분당구 정자동", "분당구"),
        ("경기도 화성시 동탄대로", "화성시"),  # 시 단위 (구 없음)
        ("부산광역시 해운대구 우동", "해운대구"),
        ("강원도 평창군 대관령면", "평창군"),
        ("제주특별자치도 제주시 노형동", "제주시"),
        ("", ""),
        ("주소불명", ""),
        ("서울특별시", ""),  # 광역만 있으면 빈 문자열
    ],
)
def test_extract_district(address, expected):
    assert extract_district(address) == expected


def test_extract_district_falsy_input():
    assert extract_district(None) == ""  # type: ignore[arg-type]


# ─── normalize_applyhome ──────────────────────────────────────────────


def _sample_apt_item(**overrides) -> dict:
    base = {
        "PBLANC_NO": "2026000123",
        "HOUSE_NM": "래미안 원펜타스",
        "SUBSCRPT_AREA_CODE": "100",
        "SUBSCRPT_AREA_CODE_NM": "",
        "RCEPT_BGNDE": "20260415",
        "RCEPT_ENDDE": "20260420",
        "HOUSE_DTL_SECD_NM": "민영",
        "HSSPLY_ADRES": "서울특별시 서초구 반포동 ...",
        "TOT_SUPLY_HSHLDCO": "641",
        "CNSTRCT_ENTRPS_NM": "삼성물산(주)",
        "PBLANC_URL": "https://www.applyhome.co.kr/...",
        "SPECLT_RDN_EARTH_AT": "Y",
        "CMPTT_PYMNT_CND_AT": "N",
    }
    base.update(overrides)
    return base


def test_normalize_applyhome_full_apt():
    result = normalize_applyhome(_sample_apt_item(), prefix="apt", category="APT")
    assert result is not None
    assert result["id"] == "apt_2026000123"
    assert result["name"] == "래미안 원펜타스"
    assert result["region"] == "서울"
    assert result["district"] == "서초구"
    assert result["period"] == "20260415 ~ 20260420"
    assert result["rcept_end"] == "20260420"
    assert result["total_units"] == "641"
    assert result["constructor"] == "삼성물산(주)"
    assert result["speculative_zone"] == "Y"
    assert result["house_category"] == "APT"


def test_normalize_applyhome_prefers_explicit_area_name_over_code_map():
    result = normalize_applyhome(
        _sample_apt_item(SUBSCRPT_AREA_CODE="100", SUBSCRPT_AREA_CODE_NM="서울특별시"),
        prefix="apt",
        category="APT",
    )
    assert result["region"] == "서울특별시"


def test_normalize_applyhome_fallback_area_code_map():
    result = normalize_applyhome(
        _sample_apt_item(SUBSCRPT_AREA_CODE="402", SUBSCRPT_AREA_CODE_NM=""),
        prefix="apt",
        category="APT",
    )
    assert result["region"] == "광주"  # AREA_CODE_MAP["402"]


def test_normalize_applyhome_unknown_area_code():
    result = normalize_applyhome(
        _sample_apt_item(SUBSCRPT_AREA_CODE="999", SUBSCRPT_AREA_CODE_NM=""),
        prefix="apt",
        category="APT",
    )
    assert result["region"] == "기타"


def test_normalize_applyhome_uses_house_manage_no_when_pblanc_no_missing():
    item = _sample_apt_item(PBLANC_NO="")
    item["HOUSE_MANAGE_NO"] = "H99999"
    result = normalize_applyhome(item, prefix="opt", category="OPT")
    assert result["id"] == "opt_H99999"


def test_normalize_applyhome_returns_none_without_id():
    item = _sample_apt_item(PBLANC_NO="")
    result = normalize_applyhome(item, prefix="apt", category="APT")
    assert result is None


def test_normalize_applyhome_no_prefix():
    result = normalize_applyhome(_sample_apt_item(), prefix="", category="APT")
    assert result["id"] == "2026000123"


def test_normalize_applyhome_house_secd_nm_fallback():
    item = _sample_apt_item(HOUSE_DTL_SECD_NM="")
    item["HOUSE_SECD_NM"] = "공공"
    result = normalize_applyhome(item, prefix="lh", category="LH")
    assert result["house_type"] == "공공"


def test_normalize_applyhome_empty_period_when_bgnde_missing():
    result = normalize_applyhome(
        _sample_apt_item(RCEPT_BGNDE=""), prefix="apt", category="APT"
    )
    assert result["period"] == ""


def test_normalize_applyhome_handles_corrupt_item():
    with mock.patch.object(common, "extract_district", side_effect=RuntimeError("boom")):
        result = normalize_applyhome(_sample_apt_item(), prefix="apt", category="APT")
    assert result is None


def test_area_code_map_covers_all_metros():
    expected_metros = {
        "서울", "인천", "경기", "부산", "대구", "광주", "대전",
        "울산", "세종", "강원", "충북", "충남", "전북", "전남",
        "경북", "경남", "제주",
    }
    assert expected_metros.issubset(set(AREA_CODE_MAP.values()))


# ─── fetch_page (재시도 로직) ─────────────────────────────────────────


def _mock_response(json_body: dict, status: int = 200):
    resp = mock.Mock()
    resp.json = mock.Mock(return_value=json_body)
    resp.status_code = status
    resp.raise_for_status = mock.Mock()
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    return resp


def test_fetch_page_success_first_attempt():
    body = {"data": [{"x": 1}], "matchCount": 1}
    with mock.patch.object(common.requests, "get", return_value=_mock_response(body)):
        result = fetch_page("http://x", {"a": "b"})
    assert result == body


def test_fetch_page_returns_empty_match_body():
    body = {"currentCount": 0, "matchCount": 0, "data": []}
    with mock.patch.object(common.requests, "get", return_value=_mock_response(body)):
        result = fetch_page("http://x", {})
    assert result == body


def test_fetch_page_returns_none_on_api_error_code():
    body = {"resultCode": "99", "resultMsg": "error"}
    with mock.patch.object(common.requests, "get", return_value=_mock_response(body)):
        result = fetch_page("http://x", {})
    assert result is None


def test_fetch_page_accepts_result_code_00():
    body = {"resultCode": "00", "data": [{"x": 1}]}
    with mock.patch.object(common.requests, "get", return_value=_mock_response(body)):
        result = fetch_page("http://x", {})
    assert result == body


def test_fetch_page_retries_on_timeout(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda *_: None)
    with mock.patch.object(
        common.requests, "get", side_effect=requests.Timeout("t/o")
    ) as get_mock:
        result = fetch_page("http://x", {})
    assert result is None
    assert get_mock.call_count == common.MAX_RETRIES


def test_fetch_page_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda *_: None)
    body = {"data": [{"x": 1}], "matchCount": 1}
    with mock.patch.object(
        common.requests,
        "get",
        side_effect=[requests.Timeout("t/o"), _mock_response(body)],
    ) as get_mock:
        result = fetch_page("http://x", {})
    assert result == body
    assert get_mock.call_count == 2


def test_fetch_page_request_exception_retried(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda *_: None)
    with mock.patch.object(
        common.requests, "get", side_effect=requests.ConnectionError("net")
    ) as get_mock:
        result = fetch_page("http://x", {})
    assert result is None
    assert get_mock.call_count == common.MAX_RETRIES


# ─── fetch_all_pages (페이지네이션) ───────────────────────────────────


def test_fetch_all_pages_single_page():
    body = {"data": [{"id": 1}, {"id": 2}], "matchCount": 2}
    with mock.patch.object(common, "fetch_page", return_value=body):
        result = fetch_all_pages("http://x", "202601", "202612", rows=50)
    assert len(result) == 2


def test_fetch_all_pages_multi_page():
    pages = [
        {"data": [{"id": i} for i in range(50)], "matchCount": 75},
        {"data": [{"id": i} for i in range(50, 75)], "matchCount": 75},
    ]
    with mock.patch.object(common, "fetch_page", side_effect=pages):
        result = fetch_all_pages("http://x", "202601", "202612", rows=50)
    assert len(result) == 75


def test_fetch_all_pages_empty_data_breaks_loop():
    body = {"data": [], "matchCount": 0}
    with mock.patch.object(common, "fetch_page", return_value=body) as mocked:
        result = fetch_all_pages("http://x", "202601", "202612")
    assert result == []
    assert mocked.call_count == 1


def test_fetch_all_pages_fetch_failure_breaks():
    with mock.patch.object(common, "fetch_page", return_value=None):
        result = fetch_all_pages("http://x", "202601", "202612")
    assert result == []


# ─── fetch_size_map ──────────────────────────────────────────────────


def test_fetch_size_map_classifies_areas():
    items = [
        {"PBLANC_NO": "001", "SUPLY_AR": "59.99"},
        {"PBLANC_NO": "001", "SUPLY_AR": "84.0"},
        {"PBLANC_NO": "002", "SUPLY_AR": "120.5"},
        {"PBLANC_NO": "003", "SUPLY_AR": "59.0"},
        {"PBLANC_NO": "003", "SUPLY_AR": "85.0"},
    ]
    with mock.patch.object(common, "fetch_all_pages", return_value=items):
        size_map = fetch_size_map("http://mdl", "202601", "202612")
    assert size_map["001"] == "소형/중형"
    assert size_map["002"] == "대형"
    assert size_map["003"] == "소형/중형"


def test_fetch_size_map_skips_invalid_area():
    items = [
        {"PBLANC_NO": "001", "SUPLY_AR": "abc"},
        {"PBLANC_NO": "001", "SUPLY_AR": "70"},
    ]
    with mock.patch.object(common, "fetch_all_pages", return_value=items):
        size_map = fetch_size_map("http://mdl", "202601", "202612")
    assert size_map["001"] == "중형"


def test_fetch_size_map_skips_missing_pblanc_no():
    items = [
        {"PBLANC_NO": "", "SUPLY_AR": "70"},
        {"HOUSE_MANAGE_NO": "H1", "SUPLY_AR": "70"},
    ]
    with mock.patch.object(common, "fetch_all_pages", return_value=items):
        size_map = fetch_size_map("http://mdl", "202601", "202612")
    assert "" not in size_map
    assert size_map.get("H1") == "중형"


def test_fetch_size_map_size_order_consistent():
    items = [
        {"PBLANC_NO": "001", "SUPLY_AR": "120"},
        {"PBLANC_NO": "001", "SUPLY_AR": "50"},
        {"PBLANC_NO": "001", "SUPLY_AR": "80"},
    ]
    with mock.patch.object(common, "fetch_all_pages", return_value=items):
        size_map = fetch_size_map("http://mdl", "202601", "202612")
    assert size_map["001"] == "소형/중형/대형"


def test_fetch_size_map_handles_non_dict_items():
    items = [None, "string", {"PBLANC_NO": "001", "SUPLY_AR": "70"}]
    with mock.patch.object(common, "fetch_all_pages", return_value=items):
        size_map = fetch_size_map("http://mdl", "202601", "202612")
    assert size_map == {"001": "중형"}
