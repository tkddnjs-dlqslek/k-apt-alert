"""오피스텔/도시형생활주택/민간임대 조회."""

import logging
from datetime import datetime, timedelta

from config import OFFICETELL_API_URL, OFFICETELL_MDL_API_URL
from crawlers.common import fetch_all_pages, fetch_size_map, normalize_applyhome

logger = logging.getLogger(__name__)


def fetch(months_back: int = 1, active_only: bool = True) -> list[dict]:
    now = datetime.now()
    start = now - timedelta(days=30 * months_back)
    startmonth = start.strftime("%Y%m")
    endmonth = now.strftime("%Y%m")

    all_items = fetch_all_pages(OFFICETELL_API_URL, startmonth, endmonth)
    size_map = fetch_size_map(OFFICETELL_MDL_API_URL, startmonth, endmonth)

    today = now.strftime("%Y%m%d")
    seen_ids: set = set()
    results: list[dict] = []

    for item in all_items:
        if not isinstance(item, dict):
            continue
        ann = normalize_applyhome(item, "oft", "오피스텔/도시형")
        if not ann or ann["id"] in seen_ids:
            continue
        if active_only and ann["rcept_end"] and ann["rcept_end"] < today:
            continue
        raw_id = ann["id"].replace("oft_", "")
        ann["size"] = size_map.get(raw_id, "")
        seen_ids.add(ann["id"])
        results.append(ann)

    logger.info(f"오피스텔: {len(results)} announcements ({startmonth}~{endmonth})")
    return results
