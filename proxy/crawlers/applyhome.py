"""APT 일반분양 조회."""

import logging
from datetime import datetime, timedelta

from config import APPLYHOME_API_URL, APPLYHOME_MDL_API_URL
from crawlers.common import fetch_all_pages, fetch_size_map, normalize_applyhome

logger = logging.getLogger(__name__)


def fetch(months_back: int = 2, active_only: bool = True) -> list[dict]:
    now = datetime.now()
    start = now - timedelta(days=30 * months_back)
    startmonth = start.strftime("%Y%m")
    endmonth = now.strftime("%Y%m")

    all_items = fetch_all_pages(APPLYHOME_API_URL, startmonth, endmonth)
    size_map = fetch_size_map(APPLYHOME_MDL_API_URL, startmonth, endmonth)

    today = now.strftime("%Y%m%d")
    seen_ids: set = set()
    results: list[dict] = []

    for item in all_items:
        if not isinstance(item, dict):
            continue
        ann = normalize_applyhome(item, "", "APT")
        if not ann or ann["id"] in seen_ids:
            continue
        if active_only and ann["rcept_end"] and ann["rcept_end"] < today:
            continue
        ann["size"] = size_map.get(ann["id"], "")
        seen_ids.add(ann["id"])
        results.append(ann)

    logger.info(f"APT: {len(results)} announcements ({startmonth}~{endmonth})")
    return results
