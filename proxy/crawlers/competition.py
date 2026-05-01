"""청약홈 경쟁률·당첨가점 실제 데이터 조회.

접수 마감 후 발표된 공고의 경쟁률과 당첨가점 분포를 청약홈 HTML 페이지와
공공데이터포털 결과 API에서 수집한다.

우선순위:
1. 청약홈 결과 페이지 HTML 파싱 (단일 공고)
2. 공공데이터포털 getAPTRsflInfo API (지역 과거 이력)
3. 실패 시 None 반환 → main.py에서 scoring.estimate_competition() 폴백
"""

import logging
import re
import time
from datetime import datetime, timedelta
from threading import Lock

import requests
from bs4 import BeautifulSoup

from config import DATA_GO_KR_API_KEY, API_REQUEST_TIMEOUT, APPLYHOME_RSFL_API_URL
from crawlers.common import AREA_CODE_MAP

logger = logging.getLogger(__name__)

# 결과 페이지 캐시 — 발표 후 변경 없으므로 24시간 TTL
RESULT_CACHE_TTL = 86400
_result_cache: dict = {}
_result_cache_lock = Lock()

HTTP_TIMEOUT = 12

# 당첨자 발표 결과 페이지 URL 템플릿
APPLYHOME_RESULT_URL = (
    "https://www.applyhome.co.kr/ai/aib/forSaleNmFirstPriority.do"
)

# 경쟁률 파싱 패턴 — "15.30 : 1" / "15.3:1" / "15 : 1"
_RATE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*:\s*1")

# 당첨가점 패턴 — "최저 45점 / 최고 72점 / 평균 58점" 형태
_SCORE_PATTERNS = {
    "min": re.compile(r"최저\s*[가격점]?\s*(\d+)\s*점?"),
    "max": re.compile(r"최고\s*[가격점]?\s*(\d+)\s*점?"),
    "avg": re.compile(r"평균\s*[가격점]?\s*(\d+(?:\.\d+)?)\s*점?"),
}


def fetch_result(pblanc_no: str) -> dict | None:
    """단일 공고 경쟁률·당첨가점 조회 (청약홈 결과 HTML 파싱).

    Args:
        pblanc_no: 공고번호 (순수 숫자, 예: "2026000123")

    Returns:
        {
          "pblanc_no": str,
          "competition_rate": float | None — 대표 경쟁률 (가중평균),
          "cutoff_min": int | None — 당첨가점 최저,
          "cutoff_max": int | None — 당첨가점 최고,
          "cutoff_avg": float | None — 당첨가점 평균,
          "detail": list[dict] — 주택유형별 세부 결과,
          "source": "applyhome_html",
        }
        또는 None (페이지 접근 불가 / 결과 미발표)
    """
    now = time.time()
    with _result_cache_lock:
        entry = _result_cache.get(pblanc_no)
        if entry and now - entry["ts"] < RESULT_CACHE_TTL:
            return entry["data"]

    try:
        resp = requests.get(
            APPLYHOME_RESULT_URL,
            params={"pblancNo": pblanc_no},
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 k-apt-alert/2.5"},
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"competition fetch_result({pblanc_no}): {e}")
        return None

    data = _parse_result_html(resp.text, pblanc_no)

    with _result_cache_lock:
        _result_cache[pblanc_no] = {"ts": now, "data": data}

    return data


def _parse_result_html(html: str, pblanc_no: str) -> dict | None:
    """청약홈 당첨자 발표 결과 페이지 HTML → 경쟁률·가점 구조체."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    text = soup.get_text(" ", strip=True)

    # 결과 미발표 or 해당 없음 체크
    if "결과가 없습니다" in text or "해당 공고가 없" in text:
        return None

    detail: list[dict] = []

    # 경쟁률 테이블 파싱 — th/td row 기반
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if not cells:
                continue

            # 경쟁률이 포함된 행 감지
            row_text = " ".join(cells)
            rate_match = _RATE_PATTERN.search(row_text)
            if not rate_match:
                continue

            rate = float(rate_match.group(1))
            house_type = cells[0] if len(cells) > 1 else ""

            entry: dict = {"house_type": house_type, "competition_rate": rate}

            # 같은 행에서 가점 추출
            for key, pat in _SCORE_PATTERNS.items():
                m = pat.search(row_text)
                if m:
                    entry[f"cutoff_{key}"] = (
                        float(m.group(1)) if "." in m.group(1) else int(m.group(1))
                    )

            detail.append(entry)

    if not detail:
        # 테이블 파싱 실패 시 전체 텍스트에서 경쟁률 추출
        rates = _RATE_PATTERN.findall(text)
        if not rates:
            return None
        rate = float(rates[0])
        detail = [{"house_type": "", "competition_rate": rate}]

    # 가중평균 경쟁률
    avg_rate = sum(d["competition_rate"] for d in detail) / len(detail)

    # 가점 집계
    mins = [d["cutoff_min"] for d in detail if "cutoff_min" in d]
    maxs = [d["cutoff_max"] for d in detail if "cutoff_max" in d]
    avgs = [d["cutoff_avg"] for d in detail if "cutoff_avg" in d]

    return {
        "pblanc_no": pblanc_no,
        "competition_rate": round(avg_rate, 1),
        "cutoff_min": min(mins) if mins else None,
        "cutoff_max": max(maxs) if maxs else None,
        "cutoff_avg": round(sum(avgs) / len(avgs), 1) if avgs else None,
        "detail": detail,
        "source": "applyhome_html",
    }


def fetch_regional_history(
    region: str,
    house_category: str = "APT",
    months_back: int = 12,
) -> list[dict]:
    """유사 지역 과거 청약 결과 목록 (공공데이터포털 getAPTRsflInfo API).

    Args:
        region: 지역명 (예: "서울", "경기")
        house_category: 공고 카테고리 (현재 "APT"만 지원)
        months_back: 조회 기간 (월 단위)

    Returns:
        list of {
          "pblanc_no": str,
          "name": str,
          "region": str,
          "competition_rate": float | None,
          "cutoff_avg": float | None,
          "rcept_end": str,
        }
    """
    if house_category != "APT":
        return []

    now = datetime.now()
    start = now - timedelta(days=30 * months_back)
    startmonth = start.strftime("%Y%m")
    endmonth = now.strftime("%Y%m")

    # 지역 코드 역매핑
    region_code = next(
        (k for k, v in AREA_CODE_MAP.items() if v == region), None
    )

    params = {
        "serviceKey": DATA_GO_KR_API_KEY,
        "pageNo": "1",
        "numOfRows": "100",
        "startmonth": startmonth,
        "endmonth": endmonth,
    }
    if region_code:
        params["subscrptAreaCode"] = region_code

    try:
        resp = requests.get(
            APPLYHOME_RSFL_API_URL,
            params=params,
            timeout=API_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        logger.warning(f"fetch_regional_history({region}): {e}")
        return []

    items = body.get("data", [])
    if not items and "response" in body:
        rb = body["response"].get("body", {})
        raw = rb.get("items", {})
        items = raw.get("item", []) if isinstance(raw, dict) else raw
        if isinstance(items, dict):
            items = [items]

    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        pblanc_no = str(item.get("PBLANC_NO") or item.get("HOUSE_MANAGE_NO") or "")
        if not pblanc_no:
            continue

        rate_raw = item.get("CMPTT_AUTO_HSHLDCO") or item.get("CMPTT_RATE") or ""
        try:
            rate: float | None = float(rate_raw) if rate_raw else None
        except ValueError:
            rate = None

        score_raw = item.get("LWET_SCORE") or item.get("AVG_SCORE") or ""
        try:
            cutoff: float | None = float(score_raw) if score_raw else None
        except ValueError:
            cutoff = None

        area_nm = item.get("SUBSCRPT_AREA_CODE_NM") or AREA_CODE_MAP.get(
            str(item.get("SUBSCRPT_AREA_CODE", "")), ""
        )

        results.append({
            "pblanc_no": pblanc_no,
            "name": item.get("HOUSE_NM", ""),
            "region": area_nm,
            "competition_rate": rate,
            "cutoff_avg": cutoff,
            "rcept_end": item.get("RCEPT_ENDDE", ""),
        })

    logger.info(f"fetch_regional_history({region}, {months_back}mo): {len(results)} results")
    return results
