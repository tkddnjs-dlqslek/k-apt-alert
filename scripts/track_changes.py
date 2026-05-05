"""일일 공고 변동 추적 스크립트.

GitHub Actions가 매일 호출:
  1. 프록시에서 현재 공고 전체 fetch
  2. 어제 snapshot과 비교 → new/updated/removed diff
  3. data 디렉터리에 오늘 snapshot + 누적 changes.json 갱신

git 커밋·푸시는 워크플로 측에서 수행 (이 스크립트는 파일만 만든다).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

PROXY = os.environ.get("PROXY_URL", "https://k-apt-alert-proxy.onrender.com").rstrip("/")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
SNAPSHOT_DIR = DATA_DIR / "snapshots"
CHANGES_FILE = DATA_DIR / "changes.json"
RETENTION_DAYS = 30

# diff 비교 대상 필드 (이게 바뀌면 'updated' 로 분류)
TRACKED_FIELDS = (
    "name", "region", "district", "address", "period", "rcept_end",
    "winner_date", "contract_start", "contract_end",
    "total_units", "house_type", "constructor", "url",
    "speculative_zone", "price_controlled", "house_category", "size",
)


def fetch_announcements() -> list[dict]:
    """프록시에서 현재 active 공고 전체 수집."""
    url = f"{PROXY}/v1/apt/announcements?category=all&active_only=true"
    req = urllib.request.Request(url, headers={"User-Agent": "k-apt-alert-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    if "announcements" not in data:
        raise RuntimeError(f"unexpected response: {list(data.keys())}")
    return data["announcements"]


def load_snapshot(d: date) -> dict[str, dict] | None:
    """{ann_id: ann_dict} 형태로 변환된 snapshot 로드. 없으면 None."""
    f = SNAPSHOT_DIR / f"{d.isoformat()}.json"
    if not f.exists():
        return None
    raw = json.loads(f.read_text(encoding="utf-8"))
    return {a["id"]: a for a in raw if a.get("id")}


def save_snapshot(d: date, anns: list[dict]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    f = SNAPSHOT_DIR / f"{d.isoformat()}.json"
    f.write_text(
        json.dumps(anns, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def diff_snapshots(prev: dict[str, dict], curr: dict[str, dict]) -> list[dict]:
    """어제 → 오늘 변화 항목만 반환."""
    changes: list[dict] = []
    today = date.today().isoformat()

    # 신규
    for aid in curr.keys() - prev.keys():
        changes.append({
            "id": aid,
            "type": "new",
            "detected_at": today,
            "name": curr[aid].get("name"),
            "region": curr[aid].get("region"),
            "district": curr[aid].get("district"),
            "house_category": curr[aid].get("house_category"),
            "url": curr[aid].get("url"),
        })

    # 사라짐 (마감 또는 삭제)
    for aid in prev.keys() - curr.keys():
        changes.append({
            "id": aid,
            "type": "removed",
            "detected_at": today,
            "name": prev[aid].get("name"),
            "region": prev[aid].get("region"),
            "url": prev[aid].get("url"),
        })

    # 변경 (필드 비교)
    for aid in prev.keys() & curr.keys():
        p, c = prev[aid], curr[aid]
        field_changes = {}
        for f in TRACKED_FIELDS:
            if p.get(f) != c.get(f):
                field_changes[f] = {"before": p.get(f), "after": c.get(f)}
        if field_changes:
            changes.append({
                "id": aid,
                "type": "updated",
                "detected_at": today,
                "name": c.get("name"),
                "region": c.get("region"),
                "url": c.get("url"),
                "field_changes": field_changes,
            })

    return changes


def merge_changes_log(new_changes: list[dict]) -> dict:
    """기존 changes.json에 오늘 변경 추가, 30일 초과분 제거."""
    if CHANGES_FILE.exists():
        log = json.loads(CHANGES_FILE.read_text(encoding="utf-8"))
    else:
        log = {"changes": [], "updated_at": ""}

    cutoff = (date.today() - timedelta(days=RETENTION_DAYS)).isoformat()
    kept = [c for c in log.get("changes", []) if c.get("detected_at", "") >= cutoff]
    merged = new_changes + kept  # 최신 순

    return {
        "changes": merged,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "retention_days": RETENTION_DAYS,
        "tracked_fields": list(TRACKED_FIELDS),
    }


def cleanup_old_snapshots() -> int:
    """RETENTION_DAYS 이상 지난 snapshot 파일 제거."""
    if not SNAPSHOT_DIR.exists():
        return 0
    cutoff = date.today() - timedelta(days=RETENTION_DAYS)
    removed = 0
    for f in SNAPSHOT_DIR.glob("*.json"):
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if d < cutoff:
            f.unlink()
            removed += 1
    return removed


def main() -> int:
    today = date.today()
    yesterday = today - timedelta(days=1)

    print(f"[track_changes] today={today} yesterday={yesterday}")
    print(f"[track_changes] proxy={PROXY}")

    try:
        anns = fetch_announcements()
    except Exception as e:
        print(f"[track_changes] FETCH FAILED: {e}", file=sys.stderr)
        return 1

    print(f"[track_changes] fetched {len(anns)} announcements")
    save_snapshot(today, anns)

    prev = load_snapshot(yesterday)
    if prev is None:
        print(f"[track_changes] no snapshot for {yesterday} — bootstrap mode (no diff)")
        # 빈 changes로 로그만 갱신
        log = merge_changes_log([])
    else:
        curr = {a["id"]: a for a in anns if a.get("id")}
        new_changes = diff_snapshots(prev, curr)
        print(f"[track_changes] diff: {sum(1 for c in new_changes if c['type'] == 'new')} new, "
              f"{sum(1 for c in new_changes if c['type'] == 'updated')} updated, "
              f"{sum(1 for c in new_changes if c['type'] == 'removed')} removed")
        log = merge_changes_log(new_changes)

    CHANGES_FILE.write_text(
        json.dumps(log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    n_removed = cleanup_old_snapshots()
    if n_removed:
        print(f"[track_changes] cleaned up {n_removed} old snapshots")

    print(f"[track_changes] total in log: {len(log['changes'])} changes (last {RETENTION_DAYS}d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
