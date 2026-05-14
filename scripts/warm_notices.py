"""GH/SH 공고 notice raw 사전 추출 — data/notices/ 캐시 워밍.

GitHub Actions가 매일 호출:
  1. 프록시에서 GH·SH 공고 목록 fetch (일정이 PDF/HWP 안에 있어 느린 카테고리)
  2. 각 공고의 notice raw 호출 → PDF/HWP 추출 결과 받음
  3. data/notices/{id}.json 으로 저장 (proxy가 인메모리 캐시 miss 시 여기서 읽음)
  4. 30일 이상 지난 notices 파일 정리

git 커밋·푸시는 워크플로 측에서 수행 (이 스크립트는 파일만 만든다).

왜 GH/SH만? — 청약홈·LH는 HTML 본문에 정보가 있어 추출이 빠름(수초).
GH/SH는 PDF/HWP 첨부 다운로드+파싱이라 2~5분 → 미리 캐시해두면 사용자 조회 시 즉시.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

PROXY = os.environ.get("PROXY_URL", "https://k-apt-alert-proxy.onrender.com").rstrip("/")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
NOTICES_DIR = DATA_DIR / "notices"
RETENTION_DAYS = 30

# notice raw 호출 타임아웃 — PDF 다운로드+파싱 포함이라 넉넉히
NOTICE_TIMEOUT = 280


def fetch_gh_sh_ids() -> list[str]:
    """GH·SH 카테고리 공고 id 목록 (active 무관 — 마감된 것도 일정 확인 가치 있음)."""
    ids: list[str] = []
    for cat in ("gh", "sh"):
        url = f"{PROXY}/v1/apt/announcements?category={cat}&active_only=false"
        req = urllib.request.Request(url, headers={"User-Agent": "notice-warmer/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=200) as r:
                data = json.loads(r.read().decode("utf-8"))
            for a in data.get("announcements", []):
                if a.get("id"):
                    ids.append(a["id"])
        except Exception as e:
            print(f"[warm] {cat} 목록 fetch 실패: {e}", file=sys.stderr)
    return ids


def warm_one(notice_id: str) -> dict | None:
    """단일 공고 notice raw 호출 → 추출 결과 반환. 실패 시 None."""
    url = f"{PROXY}/v1/apt/notice/{notice_id}/raw?force_refresh=true"
    req = urllib.request.Request(url, headers={"User-Agent": "notice-warmer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=NOTICE_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
        if "detail" in data:
            print(f"[warm] {notice_id}: proxy error — {str(data['detail'])[:80]}")
            return None
        return data
    except Exception as e:
        print(f"[warm] {notice_id}: 호출 실패 — {e}")
        return None


def save_notice(notice_id: str, data: dict) -> None:
    NOTICES_DIR.mkdir(parents=True, exist_ok=True)
    # 워밍 메타 추가 (언제 캐시됐는지)
    data["_warmed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    f = NOTICES_DIR / f"{notice_id}.json"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_old_notices() -> int:
    """RETENTION_DAYS 이상 지난 notices 파일 제거 (_warmed_at 기준)."""
    if not NOTICES_DIR.exists():
        return 0
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    removed = 0
    for f in NOTICES_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            warmed = d.get("_warmed_at", "")
            if warmed:
                wt = datetime.fromisoformat(warmed.rstrip("Z"))
                if wt < cutoff:
                    f.unlink()
                    removed += 1
        except Exception:
            continue
    return removed


def main() -> int:
    print(f"[warm] proxy={PROXY}")
    ids = fetch_gh_sh_ids()
    if not ids:
        print("[warm] GH/SH 공고 0건 — 워밍할 것 없음")
        return 0

    print(f"[warm] GH/SH 공고 {len(ids)}건 — 순차 notice raw 호출")
    ok, fail = 0, 0
    for i, notice_id in enumerate(ids, 1):
        print(f"[warm] ({i}/{len(ids)}) {notice_id} ...", flush=True)
        result = warm_one(notice_id)
        if result:
            save_notice(notice_id, result)
            ok += 1
            kinds = result.get("attachment_kinds", [])
            print(f"[warm]   → 저장 (char={result.get('char_count')}, kinds={kinds})")
        else:
            fail += 1
        # 프록시 부담 완화 — 호출 간 짧은 간격
        if i < len(ids):
            time.sleep(3)

    n_removed = cleanup_old_notices()
    print(f"[warm] 완료: {ok} 성공, {fail} 실패, {n_removed} 만료 정리")
    return 0


if __name__ == "__main__":
    sys.exit(main())
