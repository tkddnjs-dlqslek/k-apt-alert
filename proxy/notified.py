"""중복 알림 방지 (서버 측 in-memory dedup).

Render free tier는 ephemeral filesystem이라 파일 영속화가 무의미.
in-memory dict로 (channel_fingerprint, ann_id) 조합을 7일 윈도우로 관리.
서버 재시작 시 윈도우 초기화 → 한계로 명시.
"""

import time
from hashlib import sha256
from threading import Lock

DEDUP_WINDOW_SECONDS = 7 * 24 * 3600  # 7일
MAX_ENTRIES = 10000  # 메모리 보호 — 초과 시 가장 오래된 것 LRU 정리

_store: dict[str, float] = {}  # key=hash(channel|ann_id) → ts
_lock = Lock()


def _channel_key(channel: str) -> str:
    """webhook URL이나 chat_id를 그대로 메모리에 두지 않기 위해 해시."""
    return sha256(channel.encode("utf-8")).hexdigest()[:16]


def _entry_key(channel: str, ann_id: str) -> str:
    return f"{_channel_key(channel)}|{ann_id}"


def _gc_locked(now: float) -> None:
    """만료 entry 청소. 호출자가 lock 보유 가정."""
    expired = [k for k, ts in _store.items() if now - ts > DEDUP_WINDOW_SECONDS]
    for k in expired:
        _store.pop(k, None)

    # 메모리 상한 초과 시 오래된 순서로 LRU 정리
    if len(_store) > MAX_ENTRIES:
        sorted_items = sorted(_store.items(), key=lambda x: x[1])
        for k, _ in sorted_items[: len(_store) - MAX_ENTRIES]:
            _store.pop(k, None)


def filter_already_notified(channel: str, anns: list[dict]) -> tuple[list[dict], list[str]]:
    """이미 발송된 공고 제거. (남은 공고, 차단된 ID 리스트) 반환."""
    if not channel or not anns:
        return list(anns), []

    now = time.time()
    with _lock:
        _gc_locked(now)
        kept: list[dict] = []
        blocked: list[str] = []
        for a in anns:
            ann_id = str(a.get("id", ""))
            if not ann_id:
                kept.append(a)
                continue
            if _entry_key(channel, ann_id) in _store:
                blocked.append(ann_id)
            else:
                kept.append(a)
        return kept, blocked


def mark_notified(channel: str, anns: list[dict]) -> int:
    """발송 성공한 공고를 dedup store에 등록. 등록 건수 반환."""
    if not channel or not anns:
        return 0
    now = time.time()
    count = 0
    with _lock:
        for a in anns:
            ann_id = str(a.get("id", ""))
            if not ann_id:
                continue
            _store[_entry_key(channel, ann_id)] = now
            count += 1
    return count


def stats() -> dict:
    """디버그용 — 현재 추적 중인 entry 수와 윈도우."""
    now = time.time()
    with _lock:
        ages = [int(now - ts) for ts in _store.values()]
    return {
        "tracked_entries": len(ages),
        "window_seconds": DEDUP_WINDOW_SECONDS,
        "max_entries": MAX_ENTRIES,
        "oldest_age_seconds": max(ages) if ages else 0,
        "newest_age_seconds": min(ages) if ages else 0,
    }


def reset() -> int:
    """전체 store 초기화. 초기화된 entry 수 반환."""
    with _lock:
        n = len(_store)
        _store.clear()
    return n
