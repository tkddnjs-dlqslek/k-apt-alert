"""LH 공공분양 조회."""

import logging
from datetime import datetime, timedelta

import requests

from config import DATA_GO_KR_API_KEY, LH_NOTICE_API_URL, API_REQUEST_TIMEOUT
from crawlers.common import REGION_KEYWORDS

logger = logging.getLogger(__name__)

_SUBSCRIPTION_KEYWORDS = ["분양", "청약", "공급", "뉴홈", "행복주택", "공공주택", "입주자"]
_EXCLUDE_KEYWORDS = ["낙찰", "계약", "하자", "입찰", "용역", "공사", "물품"]

# 시/군 → 광역 매핑 (LH 제목에서 세부 지역명 추출용)
_CITY_TO_REGION = {
    # 경기
    "수원": "경기", "성남": "경기", "고양": "경기", "용인": "경기", "화성": "경기",
    "파주": "경기", "김포": "경기", "평택": "경기", "하남": "경기", "광명": "경기",
    "시흥": "경기", "남양주": "경기", "양주": "경기", "의왕": "경기", "과천": "경기",
    "구리": "경기", "안산": "경기", "안양": "경기", "부천": "경기", "의정부": "경기",
    "오산": "경기", "군포": "경기", "이천": "경기", "양평": "경기", "여주": "경기",
    "동탄": "경기", "광교": "경기", "판교": "경기", "위례": "경기", "별내": "경기",
    # 경남
    "창원": "경남", "김해": "경남", "양산": "경남", "진주": "경남", "거제": "경남", "통영": "경남",
    # 충남
    "천안": "충남", "아산": "충남", "서산": "충남", "당진": "충남", "논산": "충남",
    # 충북
    "청주": "충북", "충주": "충북", "제천": "충북",
    # 전북
    "전주": "전북", "익산": "전북", "군산": "전북",
    # 전남
    "목포": "전남", "여수": "전남", "순천": "전남", "광양": "전남", "나주": "전남",
    # 경북
    "포항": "경북", "구미": "경북", "경산": "경북", "안동": "경북", "김천": "경북",
    # 강원
    "춘천": "강원", "원주": "강원", "강릉": "강원", "속초": "강원",
    # 제주
    "서귀포": "제주",
}

# 수도권 등 광역 키워드
_BROAD_REGION_KEYWORDS = {"수도권", "전국", "전 지역", "전지역"}


def _fetch_lh_page(page: int, num_rows: int = 50) -> tuple[list[dict], int] | None:
    """LH Notice API 페이지 조회 — apis.data.go.kr 다형 응답 처리."""
    params = {
        "serviceKey": DATA_GO_KR_API_KEY,
        "pageNo": str(page),
        "numOfRows": str(num_rows),
    }
    try:
        resp = requests.get(LH_NOTICE_API_URL, params=params, timeout=API_REQUEST_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        logger.warning(f"LH API request failed (page {page}): {e}")
        return None

    # 직접 리스트 반환 형식
    if isinstance(body, list):
        return body, len(body)

    if not isinstance(body, dict):
        logger.warning(f"LH unexpected response type: {type(body)}")
        return None

    # apis.data.go.kr 표준 중첩 형식 {"response": {"body": {"items": [...]}}}
    if "response" in body:
        rb = body["response"].get("body", {})
        items = rb.get("items", [])
        if isinstance(items, dict):
            items = items.get("item", [])
            if isinstance(items, dict):  # 단건이면 dict로 옴
                items = [items]
        total = int(rb.get("totalCount") or len(items) or 0)
        return (items if isinstance(items, list) else []), total

    # api.odcloud.kr 형식 {"data": [...], "totalCount": N}
    if "data" in body:
        items = body.get("data", [])
        total = int(body.get("totalCount") or body.get("matchCount") or len(items))
        return (items if isinstance(items, list) else []), total

    logger.warning(f"LH unknown response keys: {list(body.keys())}")
    return None


def fetch(days_back: int = 30, active_only: bool = True) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    all_notices: list[dict] = []
    page = 1

    while True:
        result = _fetch_lh_page(page)
        if result is None:
            break

        items, total = result
        if not items:
            break

        has_old = False
        for item in items:
            if not isinstance(item, dict):
                continue
            reg_date = str(item.get("BBS_WOU_DTTM", ""))[:10]
            if active_only and reg_date < cutoff:
                has_old = True
                continue
            all_notices.append(item)

        if has_old:
            break

        if page * 50 >= total:
            break
        page += 1

    seen_ids: set = set()
    results: list[dict] = []

    for notice in all_notices:
        ann = _normalize(notice)
        if ann and ann["id"] not in seen_ids:
            seen_ids.add(ann["id"])
            results.append(ann)

    logger.info(f"LH: {len(results)} announcements (last {days_back} days)")
    return results


def _normalize(notice: dict) -> dict | None:
    try:
        title = notice.get("BBS_TL", "")
        if not title:
            return None

        if not any(kw in title for kw in _SUBSCRIPTION_KEYWORDS):
            return None
        if any(kw in title for kw in _EXCLUDE_KEYWORDS):
            return None

        notice_id = str(notice.get("BBS_SN", ""))
        if not notice_id:
            return None

        reg_date = str(notice.get("BBS_WOU_DTTM", ""))[:10]

        # Infer region from title (enhanced)
        region = _infer_region(title)

        return {
            "id": f"lh_{notice_id}",
            "name": title,
            "region": region,
            "district": "",
            "address": "",
            "period": reg_date,
            "rcept_end": "",
            "total_units": "",
            "house_type": notice.get("AIS_TP_CD_NM", "") or "공공분양",
            "constructor": "LH 한국토지주택공사",
            "url": notice.get("LINK_URL", "https://apply.lh.or.kr"),
            "speculative_zone": "",
            "price_controlled": "",
            "house_category": "LH공공분양",
        }
    except Exception as e:
        logger.warning(f"LH normalize failed: {e}")
        return None


def _infer_region(title: str) -> str:
    """공고 제목에서 지역을 추론. 광역 키워드 → 시/군 → 기본 지역명 순."""
    # 1) 수도권/전국 같은 광역 키워드
    for kw in _BROAD_REGION_KEYWORDS:
        if kw in title:
            return "전국"

    # 2) 기본 광역시/도 키워드 (서울, 경기, 인천 등)
    for keyword, r in REGION_KEYWORDS.items():
        if keyword in title:
            return r

    # 3) 시/군 → 광역 매핑 (수원→경기, 창원→경남 등)
    for city, r in _CITY_TO_REGION.items():
        if city in title:
            return r

    return "전국"
