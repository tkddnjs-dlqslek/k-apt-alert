"""공통 HTTP 호출 + 표준화 유틸."""

import time
import logging
import requests

from config import DATA_GO_KR_API_KEY, API_REQUEST_TIMEOUT, MAX_RETRIES, RETRY_BASE_DELAY

logger = logging.getLogger(__name__)

AREA_CODE_MAP = {
    "100": "서울", "200": "인천", "300": "경기",
    "400": "부산", "401": "대구", "402": "광주", "403": "대전",
    "404": "울산", "405": "세종",
    "500": "강원", "600": "충북", "601": "충남",
    "700": "전북", "701": "전남", "712": "경북", "800": "경남", "900": "제주",
}

SIZE_ORDER = ["소형", "중형", "대형"]

REGION_KEYWORDS = {
    "서울": "서울", "경기": "경기", "인천": "인천",
    "부산": "부산", "대구": "대구", "광주": "광주",
    "대전": "대전", "울산": "울산", "세종": "세종",
    "강원": "강원", "충북": "충북", "충남": "충남",
    "전북": "전북", "전남": "전남", "경북": "경북",
    "경남": "경남", "제주": "제주",
}


def fetch_page(url: str, params: dict) -> dict | None:
    """단일 페이지 API 호출. 지수 백오프 재시도."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=API_REQUEST_TIMEOUT)
            resp.raise_for_status()
            body = resp.json()

            if body.get("currentCount") == 0 and body.get("matchCount") == 0:
                return body
            if "resultCode" in body and str(body["resultCode"]) not in ("00", "0"):
                logger.warning(f"API error {body.get('resultCode')}: {body.get('resultMsg')}")
                return None
            return body

        except requests.Timeout as e:
            last_error = e
            wait = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(f"Timeout (attempt {attempt + 1}/{MAX_RETRIES}) — {wait}s wait")
            time.sleep(wait)
        except requests.RequestException as e:
            last_error = e
            wait = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(f"Request failed (attempt {attempt + 1}/{MAX_RETRIES}) — {wait}s wait: {e}")
            time.sleep(wait)

    logger.error(f"Final failure ({MAX_RETRIES} attempts): {last_error}")
    return None


def fetch_all_pages(api_url: str, startmonth: str, endmonth: str, rows: int = 50) -> list[dict]:
    """페이지네이션 순회하며 전체 항목 수집."""
    all_items = []
    page = 1

    while True:
        params = {
            "serviceKey": DATA_GO_KR_API_KEY,
            "pageNo": str(page),
            "numOfRows": str(rows),
            "startmonth": startmonth,
            "endmonth": endmonth,
        }

        body = fetch_page(api_url, params)
        if body is None:
            break

        items = body.get("data", [])
        if not items:
            break

        all_items.extend(items)

        total = body.get("matchCount") or body.get("totalCount") or len(items)
        if page * rows >= total:
            break
        page += 1

    return all_items


def fetch_size_map(mdl_url: str, startmonth: str, endmonth: str) -> dict[str, str]:
    """Mdl API 호출 -> {PBLANC_NO: size_str} 반환."""
    all_items = fetch_all_pages(mdl_url, startmonth, endmonth, rows=100)

    areas_by_id: dict[str, list[float]] = {}
    for item in all_items:
        if not isinstance(item, dict):
            continue
        pblanc_no = str(item.get("PBLANC_NO") or item.get("HOUSE_MANAGE_NO") or "")
        if not pblanc_no:
            continue
        area_str = str(item.get("SUPLY_AR", "") or item.get("HOUSE_TY", ""))
        try:
            area = float(area_str)
            areas_by_id.setdefault(pblanc_no, []).append(area)
        except ValueError:
            pass

    size_map = {}
    for pblanc_no, areas in areas_by_id.items():
        categories = set()
        for a in areas:
            if a < 60:
                categories.add("소형")
            elif a <= 85:
                categories.add("중형")
            else:
                categories.add("대형")
        if categories:
            size_map[pblanc_no] = "/".join(sorted(categories, key=lambda x: SIZE_ORDER.index(x)))

    return size_map


def normalize_applyhome(item: dict, prefix: str, category: str) -> dict | None:
    """청약홈 계열 API (APT/오피스텔/잔여/임대/임의) 공통 표준화."""
    try:
        ann_id = item.get("PBLANC_NO") or item.get("HOUSE_MANAGE_NO") or ""
        if not ann_id:
            return None

        area_code = item.get("SUBSCRPT_AREA_CODE", "")
        area_name = item.get("SUBSCRPT_AREA_CODE_NM", "") or AREA_CODE_MAP.get(area_code, "기타")

        rcept_bgn = item.get("RCEPT_BGNDE", "")
        rcept_end = item.get("RCEPT_ENDDE", "")
        period = f"{rcept_bgn} ~ {rcept_end}" if rcept_bgn else ""

        house_type = (
            item.get("HOUSE_DTL_SECD_NM", "")
            or item.get("HOUSE_SECD_NM", "")
        )

        return {
            "id": f"{prefix}_{ann_id}" if prefix else str(ann_id),
            "name": item.get("HOUSE_NM", ""),
            "region": area_name,
            "address": item.get("HSSPLY_ADRES", ""),
            "period": period,
            "rcept_end": rcept_end,
            "total_units": str(item.get("TOT_SUPLY_HSHLDCO", "")),
            "house_type": house_type,
            "constructor": item.get("CNSTRCT_ENTRPS_NM", ""),
            "url": item.get("PBLANC_URL", ""),
            "speculative_zone": item.get("SPECLT_RDN_EARTH_AT", ""),
            "price_controlled": item.get("CMPTT_PYMNT_CND_AT", ""),
            "house_category": category,
        }
    except Exception as e:
        logger.warning(f"Normalize failed ({category}): {e}")
        return None
