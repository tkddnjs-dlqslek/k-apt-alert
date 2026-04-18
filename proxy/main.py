"""
k-apt-alert proxy server

공공데이터포털 청약 API를 프록시하여 사용자가 API 키 없이 청약 공고를 조회할 수 있게 합니다.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from contextlib import asynccontextmanager
from threading import Lock

import requests
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import DATA_GO_KR_API_KEY
from crawlers import applyhome, officetell, lh, remndr, pbl_pvt_rent, opt
from crawlers.applyhome_page import enrich_schedules, cache_status as enrich_cache_status

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.1, environment=os.environ.get("SENTRY_ENV", "prod"))
    except ImportError:
        pass

CACHE_TTL_SECONDS = 600  # 기본 TTL
CACHE_TTLS = {
    # 월배치 API는 짧게 잡을 이유 없음 → 1시간
    "apt": 3600,
    "pbl_pvt_rent": 1800,
    # 실시간성 있는 것은 기본값
    "officetell": 600,
    "lh": 600,
    "remndr": 600,
    "opt": 600,
}
_cache: dict = {}
_cache_lock = Lock()


def _ttl_for(cache_key: str) -> int:
    prefix = cache_key.split(":", 1)[0]
    return CACHE_TTLS.get(prefix, CACHE_TTL_SECONDS)

DAILY_CALL_LIMIT = 9000  # 공공 API 일반 키 일일 10000, 90% 지점에서 보호
_rate_counter = {"date": "", "count": 0}
_rate_lock = Lock()


def _check_rate_limit():
    """일일 호출 카운터 — 한도 임박 시 503 반환용."""
    today = datetime.now().strftime("%Y-%m-%d")
    with _rate_lock:
        if _rate_counter["date"] != today:
            _rate_counter["date"] = today
            _rate_counter["count"] = 0
        _rate_counter["count"] += 1
        return _rate_counter["count"], DAILY_CALL_LIMIT

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


def _fetch_category_with_age(key: str, label: str, fn) -> tuple[list, int]:
    """_fetch_category 대체 — items와 age_seconds 함께 반환."""
    items = _fetch_category(key, label, fn)
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        age = int(now - entry["ts"]) if entry else 0
    return items, age


def _fetch_category(key: str, label: str, fn) -> list:
    """카테고리별 fetch + in-memory 캐시 (카테고리별 TTL) + rate limit 보호 + 실패 시 stale fallback."""
    now = time.time()
    ttl = _ttl_for(key)
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry["ts"] < ttl:
            logger.info(f"[{label}] cache hit ({len(entry['items'])} items, age {int(now - entry['ts'])}s, ttl={ttl})")
            return entry["items"]

    count, limit = _check_rate_limit()
    if count > limit:
        logger.warning(f"[{label}] daily rate limit exceeded ({count}/{limit}) — serving stale cache if any")
        if entry:
            return entry["items"]
        raise RuntimeError(f"Daily API call limit reached ({limit})")

    try:
        items = fn()
        logger.info(f"[{label}] {len(items)} items fetched (cache miss, daily count={count})")
        with _cache_lock:
            _cache[key] = {"ts": now, "items": items}
        return items
    except Exception as e:
        # Fetch 실패 시 stale cache 있으면 반환 (가용성 우선)
        if entry:
            logger.warning(f"[{label}] fetch failed, serving stale ({int(now - entry['ts'])}s old): {e}")
            return entry["items"]
        raise


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


def _is_active(ann) -> bool:
    """active_only 클라이언트 사이드 필터 — rcept_end가 오늘 이후면 True."""
    rcept_end = str(ann.get("rcept_end", ""))
    if not rcept_end or len(rcept_end) < 8:
        return False
    try:
        fmt = "%Y-%m-%d" if "-" in rcept_end else "%Y%m%d"
        end_date = datetime.strptime(rcept_end[:10], fmt).date()
        return end_date >= datetime.now().date()
    except ValueError:
        return False


def _fetch_and_filter(category, active_only, months_back, region_filter, district_filter):
    """공통 조회 + 필터링 로직. 카테고리별 병렬 fetch + active_only는 클라이언트 필터."""
    # 캐시는 항상 active_only=False 기준으로 적재 (키 분리 제거) → active_only=True 요청도 캐시 재활용
    fetchers = {
        "apt": ("APT 일반분양", lambda: applyhome.fetch(months_back, False), f"apt:{months_back}"),
        "officetell": ("오피스텔/도시형", lambda: officetell.fetch(min(months_back, 1), False), f"officetell:{min(months_back,1)}"),
        "lh": ("LH 공공분양", lambda: lh.fetch(days_back=30 * months_back, active_only=False), f"lh:{months_back}"),
        "remndr": ("APT 잔여세대", lambda: remndr.fetch(months_back, False), f"remndr:{months_back}"),
        "pbl_pvt_rent": ("공공지원민간임대", lambda: pbl_pvt_rent.fetch(min(months_back, 1), False), f"pbl_pvt_rent:{min(months_back,1)}"),
        "opt": ("임의공급", lambda: opt.fetch(min(months_back, 1), False), f"opt:{min(months_back,1)}"),
    }

    if category != "all" and category not in fetchers:
        return None, None, f"Invalid category: {category}"

    targets = fetchers if category == "all" else {category: fetchers[category]}

    announcements = []
    errors = []

    with ThreadPoolExecutor(max_workers=len(targets)) as ex:
        futures = {
            ex.submit(_fetch_category, cache_key, label, fn): (key, label)
            for key, (label, fn, cache_key) in targets.items()
        }
        for fut in as_completed(futures):
            key, label = futures[fut]
            try:
                items = fut.result()
                announcements.extend(items)
            except Exception as e:
                logger.error(f"[{label}] crawl failed: {e}")
                errors.append(f"{label}: {str(e)}")

    deduped = _dedup_announcements(announcements)

    # 지역·구군 필터 (enrichment 전 선처리로 fetch 수 최소화)
    filtered = []
    for ann in deduped:
        if region_filter and ann.get("region") not in region_filter and ann.get("region") != "전국":
            continue
        if district_filter and ann.get("district") and ann.get("district") not in district_filter:
            continue
        filtered.append(ann)

    # rcept_end 공란 공고에 대해 청약홈 HTML 파싱으로 일정 보강
    filtered = enrich_schedules(filtered)

    # D-day 계산 + active_only 필터
    unique = []
    for ann in filtered:
        ann = _add_d_day(ann)
        if active_only and not _is_active(ann):
            continue
        unique.append(ann)

    return unique, errors, None


def _apply_extra_filters(anns, min_units, constructor_contains, exclude_ids):
    """세대수·시공사·제외 ID 필터."""
    result = []
    exclude = {i.strip() for i in exclude_ids.split(",") if i.strip()} if exclude_ids else set()
    kw_list = [k.strip().lower() for k in constructor_contains.split(",") if k.strip()] if constructor_contains else []
    for a in anns:
        if exclude and str(a.get("id", "")) in exclude:
            continue
        if min_units > 0:
            try:
                u = int(str(a.get("total_units", "0")).replace(",", "") or "0")
            except ValueError:
                u = 0
            if u < min_units:
                continue
        if kw_list:
            ctor = str(a.get("constructor", "")).lower()
            if not any(kw in ctor for kw in kw_list):
                continue
        result.append(a)
    return result


def _apply_reminder_filter(anns, reminder):
    """리마인더 타입별 공고 필터.
    d3  — D-3 이하 마감 임박 공고
    d1  — D-1 이하 초긴급 공고
    winners — 접수 마감 후 7~10일 (당첨자 발표 예정)
    contract — 접수 마감 후 14~21일 (계약 체결 예정)
    """
    if not reminder:
        return anns
    result = []
    for a in anns:
        d = a.get("d_day")
        if d is None:
            continue
        if reminder == "d3" and 0 <= d <= 3:
            result.append(a)
        elif reminder == "d1" and 0 <= d <= 1:
            result.append(a)
        elif reminder == "winners" and -10 <= d <= -7:
            result.append(a)
        elif reminder == "contract" and -21 <= d <= -14:
            result.append(a)
    return result


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
    min_units: int = Query(default=0, ge=0, description="최소 세대수 (대단지 필터)"),
    constructor_contains: str = Query(default="", description="시공사 키워드 필터 (쉼표 구분)"),
    exclude_ids: str = Query(default="", description="제외할 공고 ID (중복 알림 방지용)"),
    reminder: str = Query(default="", description="리마인더 타입: d3 / d1 / winners / contract"),
):
    """청약 공고 통합 조회. D-day + 필터 축 + 리마인더 모드."""
    if not DATA_GO_KR_API_KEY:
        raise HTTPException(status_code=503, detail="Server API key not configured")

    region_filter = {r.strip() for r in region.split(",") if r.strip()} if region.strip() else set()
    district_filter = {d.strip() for d in district.split(",") if d.strip()} if district.strip() else set()

    unique, errors, err_msg = _fetch_and_filter(category, active_only, months_back, region_filter, district_filter)
    if err_msg:
        raise HTTPException(status_code=400, detail=err_msg)

    unique = _apply_extra_filters(unique, min_units, constructor_contains, exclude_ids)
    unique = _apply_reminder_filter(unique, reminder)

    # 가장 오래된 카테고리 캐시 나이 = 전체 데이터의 "최신성" 기준
    max_age = 0
    fetched_keys = [category] if category != "all" else ["apt", "officetell", "lh", "remndr", "pbl_pvt_rent", "opt"]
    now = time.time()
    with _cache_lock:
        for k, entry in _cache.items():
            if any(k.startswith(fk + ":") for fk in fetched_keys):
                age = int(now - entry["ts"])
                if age > max_age:
                    max_age = age

    return {
        "count": len(unique),
        "announcements": unique,
        "errors": errors if errors else None,
        "data_age_seconds": max_age,
        "fetched_at": datetime.fromtimestamp(now - max_age).strftime("%Y-%m-%d %H:%M:%S"),
        "filters": {
            "category": category,
            "region": list(region_filter) if region_filter else "all",
            "district": list(district_filter) if district_filter else "all",
            "active_only": active_only,
            "months_back": months_back,
            "min_units": min_units,
            "constructor_contains": constructor_contains or None,
            "exclude_ids": list({i.strip() for i in exclude_ids.split(",") if i.strip()}) if exclude_ids else None,
            "reminder": reminder or None,
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
    min_units: int = Query(default=0, ge=0),
    constructor_contains: str = Query(default=""),
    exclude_ids: str = Query(default=""),
    reminder: str = Query(default="", description="리마인더: d3/d1/winners/contract"),
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

    unique = _apply_extra_filters(unique, min_units, constructor_contains, exclude_ids)

    if not unique:
        return {"sent": 0, "message": "No announcements to notify"}

    if reminder:
        active = _apply_reminder_filter(unique, reminder)
        empty_label = f"reminder={reminder}"
    else:
        active = [a for a in unique if a.get("d_day") is not None and a.get("d_day", -1) >= 0]
        empty_label = "active announcements"
    if not active:
        return {"sent": 0, "message": f"No {empty_label} to notify"}

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
        # Slack은 invalid payload/token도 2xx로 줄 수 있음 → body가 "ok"인지 명시 검증
        body_text = resp.text.strip()
        if body_text and body_text != "ok":
            logger.error(f"Slack notify 2xx but body not 'ok': {body_text[:200]}")
            raise HTTPException(
                status_code=502,
                detail=f"Slack 응답이 ok가 아님 — '{body_text[:200]}'. webhook URL 토큰을 확인하세요.",
            )
        logger.info(f"Slack notify sent: {len(active)} announcements")
        return {"sent": len(active), "message": "Slack notification sent successfully"}
    except requests.HTTPError as e:
        body = getattr(e.response, "text", "")[:200]
        logger.error(f"Slack notify HTTP error: {e} body={body}")
        raise HTTPException(status_code=502, detail=f"Slack delivery failed: HTTP {e.response.status_code} — {body}")
    except requests.Timeout:
        logger.error("Slack notify timeout")
        raise HTTPException(status_code=504, detail="Slack delivery timed out after 10s")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Slack notify failed: {e}")
        raise HTTPException(status_code=502, detail=f"Slack delivery failed: {str(e)}")


@app.get("/v1/apt/cache")
def cache_status():
    """디버깅용 — 카테고리별 캐시 상태 + 일일 호출 카운터."""
    now = time.time()
    with _cache_lock:
        entries = [
            {
                "key": key,
                "items": len(entry["items"]),
                "age_seconds": int(now - entry["ts"]),
                "ttl_remaining": max(0, CACHE_TTL_SECONDS - int(now - entry["ts"])),
            }
            for key, entry in _cache.items()
        ]
    with _rate_lock:
        rate = {"date": _rate_counter["date"], "count": _rate_counter["count"], "limit": DAILY_CALL_LIMIT}
    return {
        "entries": entries,
        "ttl_seconds": CACHE_TTL_SECONDS,
        "rate_limit": rate,
        "schedule_enrichment": enrich_cache_status(),
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
