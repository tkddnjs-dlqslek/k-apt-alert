"""
k-apt-alert proxy server

공공데이터포털 청약 API를 프록시하여 사용자가 API 키 없이 청약 공고를 조회할 수 있게 합니다.
"""

import logging
import time
from datetime import datetime
from contextlib import asynccontextmanager
from threading import Lock

import requests
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import DATA_GO_KR_API_KEY
from crawlers import applyhome, officetell, lh, remndr, pbl_pvt_rent, opt

CACHE_TTL_SECONDS = 600
_cache: dict = {}
_cache_lock = Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATA_GO_KR_API_KEY:
        logger.warning("DATA_GO_KR_API_KEY is not set — API calls will fail")
    else:
        logger.info("Proxy server started with DATA_GO_KR_API_KEY configured")
    yield


app = FastAPI(
    title="k-apt-alert proxy",
    description="공공데이터포털 청약 API 프록시 — 사용자 API 키 불필요",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _add_d_day(ann: dict) -> dict:
    """rcept_end 기반 D-day 계산."""
    rcept_end = ann.get("rcept_end", "")
    if rcept_end and len(rcept_end) >= 8:
        try:
            fmt = "%Y-%m-%d" if "-" in rcept_end else "%Y%m%d"
            end_date = datetime.strptime(rcept_end[:10], fmt).date()
            today = datetime.now().date()
            delta = (end_date - today).days
            ann["d_day"] = delta
            if delta < 0:
                ann["d_day_label"] = "마감"
            elif delta == 0:
                ann["d_day_label"] = "D-Day (오늘 마감)"
            else:
                ann["d_day_label"] = f"D-{delta}"
        except ValueError:
            ann["d_day"] = None
            ann["d_day_label"] = ""
    else:
        ann["d_day"] = None
        ann["d_day_label"] = ""
    return ann


def _fetch_category(key: str, label: str, fn) -> list:
    """카테고리별 fetch + in-memory 캐시 (TTL 10분)."""
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry["ts"] < CACHE_TTL_SECONDS:
            logger.info(f"[{label}] cache hit ({len(entry['items'])} items, age {int(now - entry['ts'])}s)")
            return entry["items"]
    items = fn()
    logger.info(f"[{label}] {len(items)} items fetched (cache miss)")
    with _cache_lock:
        _cache[key] = {"ts": now, "items": items}
    return items


def _dedup_announcements(announcements: list) -> list:
    """ID 기준 1차 + name+region+district 기준 2차 중복 제거.
    서브타입별로 같은 단지가 중복 등록되는 경우 (예: 공공지원민간임대 AP1BL/AP2BL) 제거.
    """
    seen_ids = set()
    seen_names = set()
    unique = []
    for ann in announcements:
        ann_id = ann.get("id")
        if ann_id in seen_ids:
            continue
        seen_ids.add(ann_id)

        name_key = (
            ann.get("name", "").split("(")[0].strip(),
            ann.get("region", ""),
            ann.get("district", ""),
        )
        if name_key[0] and name_key in seen_names:
            continue
        seen_names.add(name_key)

        unique.append(ann)
    return unique


def _fetch_and_filter(category, active_only, months_back, region_filter, district_filter):
    """공통 조회 + 필터링 로직."""
    fetchers = {
        "apt": ("APT 일반분양", lambda: applyhome.fetch(months_back, active_only), f"apt:{months_back}:{active_only}"),
        "officetell": ("오피스텔/도시형", lambda: officetell.fetch(min(months_back, 1), active_only), f"officetell:{min(months_back,1)}:{active_only}"),
        "lh": ("LH 공공분양", lambda: lh.fetch(days_back=30 * months_back, active_only=active_only), f"lh:{months_back}:{active_only}"),
        "remndr": ("APT 잔여세대", lambda: remndr.fetch(months_back, active_only), f"remndr:{months_back}:{active_only}"),
        "pbl_pvt_rent": ("공공지원민간임대", lambda: pbl_pvt_rent.fetch(min(months_back, 1), active_only), f"pbl_pvt_rent:{min(months_back,1)}:{active_only}"),
        "opt": ("임의공급", lambda: opt.fetch(min(months_back, 1), active_only), f"opt:{min(months_back,1)}:{active_only}"),
    }

    if category != "all" and category not in fetchers:
        return None, None, f"Invalid category: {category}"

    targets = fetchers if category == "all" else {category: fetchers[category]}

    announcements = []
    errors = []

    for key, (label, fn, cache_key) in targets.items():
        try:
            items = _fetch_category(cache_key, label, fn)
            announcements.extend(items)
        except Exception as e:
            logger.error(f"[{label}] crawl failed: {e}")
            errors.append(f"{label}: {str(e)}")

    unique = []
    for ann in _dedup_announcements(announcements):
        if region_filter and ann.get("region") not in region_filter and ann.get("region") != "전국":
            continue
        if district_filter and ann.get("district") and ann.get("district") not in district_filter:
            continue
        unique.append(_add_d_day(ann))

    return unique, errors, None


@app.get("/health")
def health():
    return {"status": "ok", "api_key_configured": bool(DATA_GO_KR_API_KEY)}


@app.get("/v1/apt/announcements")
def get_all_announcements(
    category: str = Query(default="all", description="조회 카테고리"),
    active_only: bool = Query(default=True, description="접수 마감 전 공고만"),
    months_back: int = Query(default=2, ge=1, le=12, description="조회 기간 (개월)"),
    region: str = Query(default="", description="지역 필터 (쉼표 구분)"),
    district: str = Query(default="", description="세부 지역 필터 (구/군, 쉼표 구분)"),
):
    """청약 공고 통합 조회. D-day 포함."""
    if not DATA_GO_KR_API_KEY:
        raise HTTPException(status_code=503, detail="Server API key not configured")

    region_filter = {r.strip() for r in region.split(",") if r.strip()} if region.strip() else set()
    district_filter = {d.strip() for d in district.split(",") if d.strip()} if district.strip() else set()

    unique, errors, err_msg = _fetch_and_filter(category, active_only, months_back, region_filter, district_filter)
    if err_msg:
        raise HTTPException(status_code=400, detail=err_msg)

    return {
        "count": len(unique),
        "announcements": unique,
        "errors": errors if errors else None,
        "filters": {
            "category": category,
            "region": list(region_filter) if region_filter else "all",
            "district": list(district_filter) if district_filter else "all",
            "active_only": active_only,
            "months_back": months_back,
        },
    }


@app.post("/v1/apt/notify")
def notify(
    webhook_url: str = Query(description="Slack Incoming Webhook URL"),
    category: str = Query(default="all"),
    active_only: bool = Query(default=True),
    months_back: int = Query(default=2, ge=1, le=12),
    region: str = Query(default=""),
    district: str = Query(default=""),
):
    """청약 공고 조회 후 Slack으로 자동 발송. cron/외부 스케줄러에서 호출."""
    if not DATA_GO_KR_API_KEY:
        raise HTTPException(status_code=503, detail="Server API key not configured")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="webhook_url is required")

    region_filter = {r.strip() for r in region.split(",") if r.strip()} if region.strip() else set()
    district_filter = {d.strip() for d in district.split(",") if d.strip()} if district.strip() else set()

    unique, errors, err_msg = _fetch_and_filter(category, active_only, months_back, region_filter, district_filter)
    if err_msg:
        raise HTTPException(status_code=400, detail=err_msg)

    if not unique:
        return {"sent": 0, "message": "No announcements to notify"}

    # 접수 중인 공고만 (D-day >= 0)
    active = [a for a in unique if a.get("d_day") is not None and a.get("d_day", -1) >= 0]
    if not active:
        return {"sent": 0, "message": "No active announcements"}

    # D-day 기준 정렬 (마감 임박순)
    active.sort(key=lambda x: x.get("d_day", 999))

    # Slack Block Kit 메시지 빌드
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🏠 청약 공고 알림 ({len(active)}건)", "emoji": True},
        },
        {"type": "divider"},
    ]

    for ann in active[:10]:  # 최대 10건
        name = ann.get("name", "?")
        reg = ann.get("region", "")
        dist = ann.get("district", "")
        d_label = ann.get("d_day_label", "")
        period = ann.get("period", "")
        units = ann.get("total_units", "")
        cat = ann.get("house_category", "")
        url = ann.get("url", "https://www.applyhome.co.kr")

        location = f"{reg} {dist}".strip()
        urgency = "🔴" if ann.get("d_day", 99) <= 1 else "🟡" if ann.get("d_day", 99) <= 3 else "🟢"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{urgency} {name}* — {location}\n"
                    f"📅 {period} | ⏰ {d_label} | 🏗️ {units}세대 | 📂 {cat}\n"
                    f"<{url}|청약홈 바로가기>"
                ),
            },
        })

    if len(active) > 10:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"_...외 {len(active) - 10}건 더_"},
        })

    payload = {"blocks": blocks}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"Slack notify sent: {len(active)} announcements")
        return {"sent": len(active), "message": "Slack notification sent successfully"}
    except requests.HTTPError as e:
        body = getattr(e.response, "text", "")[:200]
        logger.error(f"Slack notify HTTP error: {e} body={body}")
        raise HTTPException(status_code=502, detail=f"Slack delivery failed: HTTP {e.response.status_code} — {body}")
    except requests.Timeout:
        logger.error("Slack notify timeout")
        raise HTTPException(status_code=504, detail="Slack delivery timed out after 10s")
    except Exception as e:
        logger.error(f"Slack notify failed: {e}")
        raise HTTPException(status_code=502, detail=f"Slack delivery failed: {str(e)}")


@app.get("/v1/apt/cache")
def cache_status():
    """디버깅용 — 카테고리별 캐시 상태."""
    now = time.time()
    with _cache_lock:
        return {
            "entries": [
                {
                    "key": key,
                    "items": len(entry["items"]),
                    "age_seconds": int(now - entry["ts"]),
                    "ttl_remaining": max(0, CACHE_TTL_SECONDS - int(now - entry["ts"])),
                }
                for key, entry in _cache.items()
            ],
            "ttl_seconds": CACHE_TTL_SECONDS,
        }


@app.get("/v1/apt/categories")
def list_categories():
    """조회 가능한 청약 카테고리 목록."""
    return {
        "categories": [
            {"id": "apt", "name": "APT 일반분양", "description": "아파트 일반분양 (월 25일 배치 업데이트)"},
            {"id": "officetell", "name": "오피스텔/도시형", "description": "오피스텔, 도시형생활주택, 민간임대 (실시간)"},
            {"id": "lh", "name": "LH 공공분양", "description": "뉴홈, 행복주택 등 공공주택 (실시간)"},
            {"id": "remndr", "name": "APT 잔여세대", "description": "미계약/미분양 재공급 — 청약통장 불필요"},
            {"id": "pbl_pvt_rent", "name": "공공지원민간임대", "description": "시세 대비 저렴, 최대 10년 거주"},
            {"id": "opt", "name": "임의공급", "description": "사업주체 자율 공급 — 선착순 계약"},
        ]
    }
