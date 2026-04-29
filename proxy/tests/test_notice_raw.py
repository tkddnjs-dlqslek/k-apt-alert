"""notice_raw 추출기 unit 테스트.

requests를 monkeypatch로 차단하고 fixtures/ HTML로 검증한다.
실 네트워크가 필요한 회귀는 `pytest -m live` 별도.
"""

import sys
import time
from pathlib import Path
from unittest import mock

# conftest.py가 sys.path 보정하지만, 모듈 단독 실행 대비 한 번 더
PROXY_ROOT = Path(__file__).resolve().parent.parent
if str(PROXY_ROOT) not in sys.path:
    sys.path.insert(0, str(PROXY_ROOT))

import pytest

from crawlers import notice_raw

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _fake_response(html: str, status: int = 200):
    resp = mock.Mock()
    resp.text = html
    resp.status_code = status
    resp.raise_for_status = mock.Mock()
    if status >= 400:
        from requests import HTTPError

        resp.raise_for_status.side_effect = HTTPError(f"{status}")
    return resp


@pytest.fixture(autouse=True)
def clear_cache():
    notice_raw._cache.clear()
    yield
    notice_raw._cache.clear()


# ─── 호스트 화이트리스트 ──────────────────────────────────────────────


def test_supported_host_applyhome():
    assert notice_raw.is_supported_host("https://www.applyhome.co.kr/path?x=1")


def test_supported_host_lh():
    assert notice_raw.is_supported_host("https://apply.lh.or.kr/lhapply/foo")


def test_supported_host_sh():
    assert notice_raw.is_supported_host("https://www.i-sh.co.kr/app/lay2/program/...view.do?seq=303101")


def test_supported_host_gh():
    assert notice_raw.is_supported_host("https://www.gh.or.kr/gh/announcement-of-salerental001.do?mode=view&articleNo=1")


def test_unsupported_host_evil():
    assert not notice_raw.is_supported_host("https://evil.example.com/abc")


def test_empty_url():
    assert not notice_raw.is_supported_host("")


# ─── 청약홈 추출 ───────────────────────────────────────────────────────


def test_applyhome_pblanc_cont():
    html = _load("applyhome_pblanc_cont.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)):
        result = notice_raw.extract_notice_raw(
            notice_id="apt_001",
            url="https://www.applyhome.co.kr/test1",
            max_chars=30000,
        )
    assert result["id"] == "apt_001"
    assert result["source"] == "html"
    assert "OO지구" in result["title"]
    assert "var x = 1" not in result["text"]
    assert "© 청약홈" not in result["text"]
    assert "신청자격" in result["text"]
    assert "공급일정" in result["text"]
    assert set(result["sections"].keys()) == {"자격", "공급일정", "공급금액", "유의사항"}
    assert "무주택세대구성원" in result["sections"]["자격"]
    assert not result["truncated"]


def test_applyhome_cont_class():
    html = _load("applyhome_cont_class.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)):
        result = notice_raw.extract_notice_raw(
            notice_id="apt_002",
            url="https://www.applyhome.co.kr/test2",
            max_chars=30000,
        )
    assert "래미안" in result["title"]
    assert "투기과열지구" in result["text"]
    assert "로고 영역" not in result["text"]


def test_applyhome_no_container_falls_back_to_body():
    html = _load("applyhome_no_container.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)):
        result = notice_raw.extract_notice_raw(
            notice_id="apt_003",
            url="https://www.applyhome.co.kr/test3",
            max_chars=30000,
        )
    assert "최소 공고" in result["text"]
    assert "body fallback" in result["text"]


# ─── LH 추출 ───────────────────────────────────────────────────────────


def test_lh_board_view():
    html = _load("lh_board_view.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)):
        result = notice_raw.extract_notice_raw(
            notice_id="lh_001",
            url="https://apply.lh.or.kr/lhapply/notice/1",
            max_chars=30000,
        )
    assert "행복주택" in result["title"]
    assert "임대 보증금" in result["text"]
    assert "LH 메뉴" not in result["text"]
    assert "LH 푸터" not in result["text"]
    assert len(result["sections"]) >= 2


def test_lh_content_id():
    html = _load("lh_content_id.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)):
        result = notice_raw.extract_notice_raw(
            notice_id="lh_002",
            url="https://apply.lh.or.kr/lhapply/notice/2",
            max_chars=30000,
        )
    assert "국민임대주택" in result["title"]
    assert set(result["sections"].keys()) == {"자격", "공급일정", "공급금액", "유의사항"}


# ─── SH 추출 ───────────────────────────────────────────────────────────


def test_sh_board_view():
    html = _load("sh_view.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)):
        result = notice_raw.extract_notice_raw(
            notice_id="sh_001",
            url="https://www.i-sh.co.kr/app/lay2/program/.../m_247/view.do?seq=303101&multi_itm_seq=2",
            max_chars=30000,
        )
    assert "장기전세주택" in result["title"]
    assert "무주택세대구성원" in result["text"]
    assert "SH 메인 메뉴" not in result["text"]
    assert "SH 푸터" not in result["text"]
    assert set(result["sections"].keys()) == {"자격", "공급일정", "공급금액", "유의사항"}


# ─── GH 추출 ───────────────────────────────────────────────────────────


def test_gh_board_view():
    html = _load("gh_view.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)):
        result = notice_raw.extract_notice_raw(
            notice_id="gh_001",
            url="https://www.gh.or.kr/gh/announcement-of-salerental001.do?mode=view&articleNo=64782",
            max_chars=30000,
        )
    assert "행복주택" in result["title"]
    assert "신혼부부" in result["text"]
    assert "GH 상단 메뉴" not in result["text"]
    assert "GH 푸터" not in result["text"]
    assert len(result["sections"]) >= 2


# ─── 캐시 동작 ─────────────────────────────────────────────────────────


def test_cache_hit_avoids_second_fetch():
    html = _load("applyhome_pblanc_cont.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)) as mocked:
        notice_raw.extract_notice_raw("apt_cache", "https://www.applyhome.co.kr/c", 30000)
        notice_raw.extract_notice_raw("apt_cache", "https://www.applyhome.co.kr/c", 30000)
        assert mocked.call_count == 1


def test_force_refresh_bypasses_cache():
    html = _load("applyhome_pblanc_cont.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)) as mocked:
        notice_raw.extract_notice_raw("apt_force", "https://www.applyhome.co.kr/f", 30000)
        notice_raw.extract_notice_raw(
            "apt_force", "https://www.applyhome.co.kr/f", 30000, force_refresh=True
        )
        assert mocked.call_count == 2


def test_invalidate_removes_entry():
    html = _load("applyhome_pblanc_cont.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)):
        notice_raw.extract_notice_raw("apt_inv", "https://www.applyhome.co.kr/i", 30000)
    assert notice_raw.invalidate("apt_inv") is True
    assert notice_raw.invalidate("apt_inv") is False  # 두 번째는 없음


# ─── max_chars truncation ─────────────────────────────────────────────


def test_truncate_when_text_exceeds_max_chars():
    html = _load("applyhome_long_for_truncate.html")
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(html)):
        small = notice_raw.extract_notice_raw(
            "apt_long", "https://www.applyhome.co.kr/long", max_chars=200
        )
        large = notice_raw.extract_notice_raw(
            "apt_long", "https://www.applyhome.co.kr/long", max_chars=30000
        )
    assert small["truncated"] is True
    assert small["text"].endswith("[... truncated]")
    assert large["truncated"] is False
    assert len(small["text"]) < len(large["text"])


# ─── 에러 케이스 ───────────────────────────────────────────────────────


def test_unsupported_host_raises():
    with pytest.raises(ValueError, match="unsupported host"):
        notice_raw.extract_notice_raw(
            "x", "https://evil.example.com/abc", 30000
        )


def test_fetch_failure_raises():
    from requests import RequestException

    with mock.patch.object(notice_raw.requests, "get", side_effect=RequestException("boom")):
        with pytest.raises(ValueError, match="fetch failed"):
            notice_raw.extract_notice_raw(
                "apt_err", "https://www.applyhome.co.kr/err", 30000
            )


def test_empty_text_raises():
    empty_html = "<html><body></body></html>"
    with mock.patch.object(notice_raw.requests, "get", return_value=_fake_response(empty_html)):
        with pytest.raises(ValueError, match="empty extracted text"):
            notice_raw.extract_notice_raw(
                "apt_empty", "https://www.applyhome.co.kr/empty", 30000
            )


# ─── live 회귀 테스트 (옵셔널) ────────────────────────────────────────


@pytest.mark.live
def test_live_applyhome_smoke():
    """실제 청약홈 페이지 1건으로 회귀 — 정기 실행은 안 함, 셀렉터 변경 의심 시에만.

    실행: pytest -m live proxy/tests/test_notice_raw.py::test_live_applyhome_smoke
    환경변수 K_APT_LIVE_URL로 URL 지정 (없으면 SKIP).
    """
    import os

    url = os.environ.get("K_APT_LIVE_URL")
    if not url:
        pytest.skip("K_APT_LIVE_URL 미설정")
    if not notice_raw.is_supported_host(url):
        pytest.fail(f"K_APT_LIVE_URL이 지원 호스트가 아님: {url}")
    result = notice_raw.extract_notice_raw("live_smoke", url, 30000, force_refresh=True)
    assert result["char_count"] > 100
    assert result["title"]
