"""공고 변동 이력 조회.

`data` 브랜치에 GitHub Actions가 매일 갱신하는 changes.json을 raw URL로 fetch.
프록시는 10분 캐시 + since/type 필터링만 담당.

GitHub repo는 환경변수로 override 가능 (테스트용):
  CHANGES_GITHUB_REPO=tkddnjs-dlqslek/k-apt-alert  (default)
  CHANGES_GITHUB_BRANCH=data                       (default)
"""

from __future__ import annotations

import json
import os
import time
from threading import Lock

import requests

REPO   = os.environ.get("CHANGES_GITHUB_REPO", "tkddnjs-dlqslek/k-apt-alert")
BRANCH = os.environ.get("CHANGES_GITHUB_BRANCH", "data")
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/data/changes.json"

CACHE_TTL = 600  # 10분 — Actions가 24시간 주기라 더 짧게 가져갈 이유 없음
_cache: dict = {"ts": 0.0, "data": None}
_lock = Lock()


def _fetch_remote() -> dict:
    """raw.githubusercontent.com에서 changes.json 다운로드."""
    resp = requests.get(RAW_URL, timeout=15)
    if resp.status_code == 404:
        return {
            "changes": [],
            "updated_at": "",
            "retention_days": 30,
            "_status": "not_yet_initialized",
        }
    resp.raise_for_status()
    data = resp.json()
    data["_status"] = "ok"
    return data


def get_log(force_refresh: bool = False) -> dict:
    """캐시된 changes.json. force_refresh=True면 즉시 갱신."""
    now = time.time()
    with _lock:
        if (
            not force_refresh
            and _cache["data"] is not None
            and now - _cache["ts"] < CACHE_TTL
        ):
            return _cache["data"]
    data = _fetch_remote()
    with _lock:
        _cache["ts"] = now
        _cache["data"] = data
    return data


def filter_changes(
    log: dict,
    since: str = "",
    change_type: str = "",
    limit: int = 50,
) -> list[dict]:
    """since(YYYY-MM-DD 이후) + change_type(new/updated/removed) 필터링."""
    items = log.get("changes", [])
    if since:
        items = [c for c in items if c.get("detected_at", "") >= since]
    if change_type:
        items = [c for c in items if c.get("type") == change_type]
    return items[: max(1, min(limit, 200))]


def cache_status() -> dict:
    """디버그용 캐시 상태."""
    now = time.time()
    with _lock:
        return {
            "cached": _cache["data"] is not None,
            "age_seconds": int(now - _cache["ts"]) if _cache["ts"] else None,
            "ttl_seconds": CACHE_TTL,
            "raw_url": RAW_URL,
        }
