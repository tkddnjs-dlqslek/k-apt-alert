"""LH 공공분양 조회."""

import logging
from datetime import datetime, timedelta

from config import DATA_GO_KR_API_KEY, LH_NOTICE_API_URL
from crawlers.common import fetch_page, REGION_KEYWORDS

logger = logging.getLogger(__name__)

_SUBSCRIPTION_KEYWORDS = ["분양", "청약", "공급", "뉴홈", "행복주택", "공공주택", "입주자"]
_EXCLUDE_KEYWORDS = ["낙찰", "계약", "하자", "입찰", "용역", "공사", "물품"]


def fetch(days_back: int = 30, active_only: bool = True) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    all_notices: list[dict] = []
    page = 1

    while True:
        params = {
            "serviceKey": DATA_GO_KR_API_KEY,
            "pageNo": str(page),
            "numOfRows": "50",
        }

        body = fetch_page(LH_NOTICE_API_URL, params)
        if body is None:
            break

        items = body.get("data", [])
        if not items:
            break

        has_old = False
        for item in items:
            reg_date = str(item.get("BBS_WOU_DTTM", ""))[:10]
            if active_only and reg_date < cutoff:
                has_old = True
                continue
            all_notices.append(item)

        if has_old:
            break

        total = body.get("totalCount") or len(items)
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

        # Infer region from title
        region = "기타"
        for keyword, r in REGION_KEYWORDS.items():
            if keyword in title:
                region = r
                break

        return {
            "id": f"lh_{notice_id}",
            "name": title,
            "region": region,
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
