"""공공지원 민간임대 조회."""

import logging
from datetime import datetime, timedelta

from config import PBL_PVT_RENT_API_URL, PBL_PVT_RENT_MDL_API_URL
from crawlers.common import fetch_all_pages, fetch_size_map, normalize_applyhome

logger = logging.getLogger(__name__)


def fetch(months_back: int = 1, active_only: bool = True) -> list[dict]:
    now = datetime.now()
    start = now - timedelta(days=30 * months_back)
    startmonth = start.strftime("%Y%m")
    endmonth = now.strftime("%Y%m")

    all_items = fetch_all_pages(PBL_PVT_RENT_API_URL, startmonth, endmonth)
    size_map = fetch_size_map(PBL_PVT_RENT_MDL_API_URL, startmonth, endmonth)

    today = now.strftime("%Y%m%d")
    seen_ids: set = set()
    results: list[dict] = []

    for item in all_items:
        if not isinstance(item, dict):
            continue
        ann = normalize_applyhome(item, "ppr", "공공지원민간임대")
        if not ann or ann["id"] in seen_ids:
            continue
        if active_only and ann["rcept_end"] and ann["rcept_end"] < today:
            continue
        raw_id = ann["id"].replace("ppr_", "")
        ann["size"] = size_map.get(raw_id, "")
        seen_ids.add(ann["id"])
        results.append(ann)

    logger.info(f"공공지원민간임대: {len(results)} announcements ({startmonth}~{endmonth})")
    return results
