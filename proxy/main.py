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
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

from config import (
    DATA_GO_KR_API_KEY,
    NOTICE_MAX_CHARS_DEFAULT,
    NOTICE_RAW_DAILY_LIMIT_FREE,
    TIER_LIMITS,
)
from crawlers import applyhome, officetell, lh, remndr, pbl_pvt_rent, opt, sh, gh
from crawlers import competition as competition_crawler
from crawlers.applyhome_page import enrich_schedules, cache_status as enrich_cache_status
from crawlers.common import extract_district
from crawlers.notice_raw import (
    extract_notice_raw,
    is_supported_host,
    cache_status as notice_raw_cache_status,
    invalidate as notice_raw_invalidate,
)
import scoring
import notified as notified_store
import changes as changes_store

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
    # SH·GH는 공식 API가 아니라 HTML 크롤링이므로 더 길게 (서버 부하 배려)
    "sh": 1800,
    "gh": 1800,
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
    """rcept_end 기반 D-day 계산.

    schedule_source == "unavailable"이면 일정 모르므로 명시적으로 라벨 표시
    → LLM·사용자가 추천에서 별도 처리하도록 신호 제공.
    """
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
            ann["d_day_label"] = "⚠️ 일정 미확인"
    elif ann.get("schedule_source") == "unavailable":
        # GH/SH 등 일정 정보 부재 — 추천·정렬에서 별도 처리 필요
        ann["d_day"] = None
        ann["d_day_label"] = "⚠️ 일정 미확인 (원문 확인 필요)"
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
    """active_only 클라이언트 사이드 필터.

    1) rcept_end 있으면 → 오늘 이후만 True
    2) rcept_end 없고 schedule_source == "unavailable" (SH/GH 등 HTML 크롤러)
       → notice_date 기준 14일 이내면 True
       (GH/SH 실제 접수기간 보통 10~14일이라 30일은 너무 길었음 — 이미 마감된 공고가
        통과하던 문제. d_day_label에도 '일정 미확인'으로 표시해 LLM·사용자에게 경고.)
    """
    rcept_end = str(ann.get("rcept_end", ""))
    if rcept_end and len(rcept_end) >= 8:
        try:
            fmt = "%Y-%m-%d" if "-" in rcept_end else "%Y%m%d"
            end_date = datetime.strptime(rcept_end[:10], fmt).date()
            return end_date >= datetime.now().date()
        except ValueError:
            return False

    if ann.get("schedule_source") == "unavailable":
        notice_date = str(ann.get("notice_date", ""))
        if notice_date and len(notice_date) >= 8:
            try:
                fmt = "%Y-%m-%d" if "-" in notice_date else "%Y%m%d"
                nd = datetime.strptime(notice_date[:10], fmt).date()
                return (datetime.now().date() - nd).days <= 14
            except ValueError:
                return False

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
        "sh": ("SH 공공주택", lambda: sh.fetch(months_back, False), f"sh:{months_back}"),
        "gh": ("GH 공공주택", lambda: gh.fetch(months_back, False), f"gh:{months_back}"),
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
    # district_filter가 지정된 경우, district가 비어있는 항목은 매칭 불가로 간주하여 제외
    # — SH/GH 등 district 미설정 카테고리가 "송파구만" 요청에 전부 통과하던 문제 차단
    filtered = []
    for ann in deduped:
        if region_filter and ann.get("region") not in region_filter and ann.get("region") != "전국":
            continue
        if district_filter:
            ann_district = ann.get("district", "")
            # 1차: address에서 구/군 추출 시도 (SH/GH는 district 비어 있어도 address에 정보)
            if not ann_district:
                ann_district = extract_district(ann.get("address", "")) or ""
            if not ann_district or ann_district not in district_filter:
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
    fetched_keys = [category] if category != "all" else ["apt", "officetell", "lh", "remndr", "pbl_pvt_rent", "opt", "sh", "gh"]
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


def _build_slack_blocks(active: list[dict]) -> dict:
    """Slack Block Kit 페이로드 빌드."""
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🏠 청약 공고 알림 ({len(active)}건)", "emoji": True}},
        {"type": "divider"},
    ]
    for ann in active[:10]:
        location = f"{ann.get('region','')} {ann.get('district','')}".strip()
        urgency = "🔴" if ann.get("d_day", 99) <= 1 else "🟡" if ann.get("d_day", 99) <= 3 else "🟢"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{urgency} {ann.get('name','?')}* — {location}\n"
                    f"📅 {ann.get('period','')} | ⏰ {ann.get('d_day_label','')} | "
                    f"🏗️ {ann.get('total_units','')}세대 | 📂 {ann.get('house_category','')}\n"
                    f"<{ann.get('url','https://www.applyhome.co.kr')}|청약홈 바로가기>"
                ),
            },
        })
    if len(active) > 10:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_...외 {len(active) - 10}건 더_"}})
    return {"blocks": blocks}


def _build_telegram_text(active: list[dict]) -> str:
    """Telegram HTML parse_mode 메시지 빌드. 한 메시지에 최대 10건."""
    lines = [f"<b>🏠 청약 공고 알림 ({len(active)}건)</b>", ""]
    for ann in active[:10]:
        location = f"{ann.get('region','')} {ann.get('district','')}".strip()
        urgency = "🔴" if ann.get("d_day", 99) <= 1 else "🟡" if ann.get("d_day", 99) <= 3 else "🟢"
        name = ann.get("name", "?")
        url = ann.get("url", "https://www.applyhome.co.kr")
        lines.append(f"{urgency} <b><a href=\"{url}\">{name}</a></b> — {location}")
        lines.append(
            f"📅 {ann.get('period','')} | ⏰ {ann.get('d_day_label','')} | "
            f"🏗️ {ann.get('total_units','')}세대 | 📂 {ann.get('house_category','')}"
        )
        lines.append("")
    if len(active) > 10:
        lines.append(f"<i>...외 {len(active) - 10}건 더</i>")
    return "\n".join(lines)


def _short_hook_label(webhook_url: str) -> str:
    """Slack webhook URL → 응답·로그용 짧은 라벨. 마지막 path segment 6자."""
    if not webhook_url:
        return "default"
    try:
        tail = webhook_url.rstrip("/").rsplit("/", 1)[-1]
        return tail[-6:] if len(tail) >= 6 else tail
    except Exception:
        return "unknown"


def _send_slack(webhook_url: str, active: list[dict]) -> None:
    """Slack webhook 발송. 실패 시 HTTPException — 채널별 에러 분리 보고용.

    URL 형식 검증을 먼저 해서 한 채널이 깨졌어도 다른 채널은 계속 발송되게 한다.
    """
    if not webhook_url or not (webhook_url.startswith("http://") or webhook_url.startswith("https://")):
        raise HTTPException(
            status_code=400,
            detail=f"Slack webhook URL 형식 오류 — https:// 시작 필요 (받은 길이={len(webhook_url) if webhook_url else 0})",
        )
    payload = _build_slack_blocks(active)
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        body_text = resp.text.strip()
        if body_text and body_text != "ok":
            raise HTTPException(
                status_code=502,
                detail=f"Slack 응답이 ok가 아님 — '{body_text[:200]}'. webhook URL 토큰을 확인하세요.",
            )
        logger.info(f"Slack notify sent: {len(active)} announcements")
    except requests.HTTPError as e:
        body = getattr(e.response, "text", "")[:200]
        raise HTTPException(status_code=502, detail=f"Slack delivery failed: HTTP {e.response.status_code} — {body}")
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Slack delivery timed out after 10s")
    except requests.RequestException as e:
        # InvalidURL, ConnectionError, MissingSchema 등 모두 여기로
        raise HTTPException(status_code=502, detail=f"Slack delivery error: {type(e).__name__} — {str(e)[:200]}")


def _send_telegram(token: str, chat_id: str, active: list[dict]) -> None:
    """Telegram Bot API 발송. 실패 시 HTTPException."""
    text = _build_telegram_text(active)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            desc = data.get("description", "unknown error")
            raise HTTPException(status_code=502, detail=f"Telegram API 응답 실패 — {desc}")
        logger.info(f"Telegram notify sent: {len(active)} announcements to chat {chat_id}")
    except requests.HTTPError as e:
        body = getattr(e.response, "text", "")[:200]
        raise HTTPException(status_code=502, detail=f"Telegram delivery failed: HTTP {e.response.status_code} — {body}")
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Telegram delivery timed out after 10s")


@app.post("/v1/apt/notify")
def notify(
    webhook_url: str = Query(default="", description="Slack Webhook URL (전체 fallback). 지역별 webhook_seoul 등이 따로 있으면 그 외 지역만 이 URL로"),
    webhook_seoul: str = Query(default="", description="서울 공고 전용 Slack Webhook (옵션)"),
    webhook_gyeonggi: str = Query(default="", description="경기 공고 전용 Slack Webhook (옵션)"),
    webhook_incheon: str = Query(default="", description="인천 공고 전용 Slack Webhook (옵션)"),
    webhook_busan: str = Query(default="", description="부산 공고 전용 Slack Webhook (옵션)"),
    webhook_highlight: str = Query(default="", description="긴급 공고 전용 채널 — d_day≤1인 공고를 추가로 여기에도 발송"),
    telegram_token: str = Query(default="", description="Telegram Bot Token (텔레그램 발송)"),
    telegram_chat_id: str = Query(default="", description="Telegram Chat ID (텔레그램 발송)"),
    category: str = Query(default="all"),
    active_only: bool = Query(default=True),
    months_back: int = Query(default=2, ge=1, le=12),
    region: str = Query(default=""),
    district: str = Query(default=""),
    min_units: int = Query(default=0, ge=0),
    constructor_contains: str = Query(default=""),
    exclude_ids: str = Query(default=""),
    reminder: str = Query(default="", description="리마인더: d3/d1/winners/contract"),
    dedup: bool = Query(default=True, description="서버 측 7일 중복 알림 방지 (in-memory)"),
):
    """청약 공고 조회 후 Slack/Telegram 자동 발송.

    Slack 채널 라우팅 (apt_alert 스타일):
    - webhook_url: 전체 fallback (지역별 매핑 안 된 공고 이걸로)
    - webhook_seoul/gyeonggi/incheon/busan: 해당 지역 공고만 라우팅
    - webhook_highlight: d_day≤1 공고를 지역 채널에 추가로 한 번 더 발송

    텔레그램은 단일 chat_id (라우팅 없음).
    """
    if not DATA_GO_KR_API_KEY:
        raise HTTPException(status_code=503, detail="Server API key not configured")

    # region별 webhook 매핑 (빈 값은 무시)
    region_webhooks: dict[str, str] = {}
    for region_name, hook in [
        ("서울", webhook_seoul), ("경기", webhook_gyeonggi),
        ("인천", webhook_incheon), ("부산", webhook_busan),
    ]:
        if hook:
            region_webhooks[region_name] = hook

    has_slack = bool(webhook_url) or bool(region_webhooks) or bool(webhook_highlight)
    has_telegram = bool(telegram_token and telegram_chat_id)
    if telegram_token and not telegram_chat_id:
        raise HTTPException(status_code=400, detail="telegram_chat_id is required when telegram_token is provided")
    if not has_slack and not has_telegram:
        raise HTTPException(
            status_code=400,
            detail="Provide webhook_url (Slack), region-specific webhooks, or telegram_token + telegram_chat_id",
        )

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

    active.sort(key=lambda x: x.get("d_day", 999))

    # ─────────────────────────────────────────────────────────
    # Slack 채널 라우팅 — region별 webhook 매핑 + highlight
    # ─────────────────────────────────────────────────────────
    # slack_groups[webhook_url] = list[ann] — 같은 webhook URL에 보낼 공고들
    slack_groups: dict[str, list[dict]] = {}
    if has_slack:
        for ann in active:
            ann_region = ann.get("region", "").strip()
            target = region_webhooks.get(ann_region) or webhook_url
            if target:
                slack_groups.setdefault(target, []).append(ann)
            # highlight: d_day≤1인 공고는 별도 채널에도 추가 발송 (지역 채널과 별개)
            if webhook_highlight and ann.get("d_day", 99) <= 1:
                slack_groups.setdefault(webhook_highlight, []).append(ann)

    # 서버 측 dedup — 채널별로 따로 적용 (각 webhook URL은 고유 발송 이력)
    blocked_summary: dict = {}
    dedup_filtered_groups: dict[str, list[dict]] = {}
    if has_slack:
        for hook, items in slack_groups.items():
            if dedup:
                kept, blocked = notified_store.filter_already_notified(f"slack:{hook}", items)
                if blocked:
                    blocked_summary[f"slack:{_short_hook_label(hook)}"] = len(blocked)
                dedup_filtered_groups[hook] = kept
            else:
                dedup_filtered_groups[hook] = items

    telegram_active = active
    if has_telegram and dedup:
        telegram_active, blocked = notified_store.filter_already_notified(f"tg:{telegram_chat_id}", active)
        if blocked:
            blocked_summary["telegram"] = len(blocked)

    channels_sent: list[str] = []
    channel_errors: dict = {}
    sent_counts: dict = {}
    try:
        # Slack: 각 채널별 발송
        for hook, items in dedup_filtered_groups.items():
            label = f"slack:{_short_hook_label(hook)}"
            if not items:
                channel_errors[label] = "all announcements already notified within 7-day window"
                continue
            try:
                _send_slack(hook, items)
                channels_sent.append(label)
                sent_counts[label] = len(items)
                if dedup:
                    notified_store.mark_notified(f"slack:{hook}", items)
            except HTTPException as e:
                channel_errors[label] = e.detail

        # Telegram: 단일 채널
        if has_telegram:
            if telegram_active:
                try:
                    _send_telegram(telegram_token, telegram_chat_id, telegram_active)
                    channels_sent.append("telegram")
                    sent_counts["telegram"] = len(telegram_active)
                    if dedup:
                        notified_store.mark_notified(f"tg:{telegram_chat_id}", telegram_active)
                except HTTPException as e:
                    channel_errors["telegram"] = e.detail
            else:
                channel_errors["telegram"] = "all announcements already notified within 7-day window"
    except Exception as e:
        logger.error(f"notify unexpected: {e}")
        raise HTTPException(status_code=502, detail=f"Unexpected notify error: {e}")

    if not channels_sent:
        if blocked_summary and not any(
            isinstance(v, str) and "already notified" not in v for v in channel_errors.values()
        ):
            return {
                "sent": 0,
                "channels": [],
                "blocked_by_dedup": blocked_summary,
                "message": "All target announcements were already notified within the 7-day dedup window.",
            }
        raise HTTPException(
            status_code=502,
            detail={"message": "All configured channels failed", "errors": channel_errors},
        )
    total_sent = sum(sent_counts.values())
    return {
        "sent": total_sent,
        "sent_detail": sent_counts,
        "channels": channels_sent,
        "blocked_by_dedup": blocked_summary or None,
        "errors": channel_errors or None,
        "message": f"Sent to {', '.join(channels_sent)}",
    }


@app.post("/v1/apt/score")
def score_profile(payload: dict):
    """결정론적 가점 + 특공 자격 계산.

    Request body:
        {
          "profile": {
            "no_house_years": 3.5,
            "dependents": 2,
            "subscription_account": {
              "years": 7.0,
              "minor_years_pre_2024": 0,
              "minor_years_post_2024": 0
            },
            "no_house": true,
            "ever_owned_house": false,
            "marriage_date": "2022-03-15",  // 선택
            "children": [{"age": 5}, {"age": 2}],
            "dependent_parents_3y": false,
            "age": 32
          },
          "specials": ["신혼부부", "생애최초", "다자녀"]  // 선택, 기본 4종 전부
        }

    프로필은 서버에 저장되지 않고 응답 후 즉시 폐기됩니다.
    """
    profile = payload.get("profile") or payload  # body 자체가 profile일 때도 허용
    if not isinstance(profile, dict):
        raise HTTPException(status_code=400, detail="profile must be an object")
    specials = payload.get("specials") or ["신혼부부", "생애최초", "다자녀", "노부모부양", "청년"]

    scores = scoring.calc_total_score(profile)
    eligibility = {}
    for s in specials:
        ok, reason = scoring.is_eligible_special(profile, s)
        eligibility[s] = {"eligible": ok, "reason": reason}

    # 공고 리스트가 함께 오면 각 공고별 1순위 판정도 포함
    anns = payload.get("announcements", [])
    priority_checks = None
    if isinstance(anns, list) and anns:
        priority_checks = [
            {"id": a.get("id"), **scoring.is_eligible_first_priority(profile, a)}
            for a in anns
        ]

    result = {"scores": scores, "specials": eligibility}
    if priority_checks is not None:
        result["priority_checks"] = priority_checks
    return result


@app.post("/v1/apt/match")
def match_announcements(payload: dict):
    """프로필과 공고 리스트의 카테고리/지역/세대수 적합도 계산.

    Request body:
        {
          "profile": {
            "preferred_categories": ["APT", "공공지원민간임대"],
            "preferred_regions": ["서울", "경기"],
            "min_units": 300
          },
          "announcements": [{...}, {...}]
        }
    """
    profile = payload.get("profile", {})
    anns = payload.get("announcements", [])
    if not isinstance(anns, list):
        raise HTTPException(status_code=400, detail="announcements must be a list")

    results = []
    for a in anns:
        m = scoring.match_announcement(profile, a)
        results.append({"id": a.get("id"), "name": a.get("name"), **m})
    return {"matches": results, "count": len(results)}


@app.get("/v1/apt/dedup/stats")
def dedup_stats():
    """서버 측 중복 알림 방지 store 상태."""
    return notified_store.stats()


@app.post("/v1/apt/dedup/reset")
def dedup_reset():
    """dedup store 전체 초기화. 운영자용."""
    cleared = notified_store.reset()
    return {"cleared_entries": cleared}


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
        "dedup": notified_store.stats(),
    }


@app.get("/v1/apt/announcements/{ann_id}/ics")
def export_calendar_ics(ann_id: str):
    """공고 청약 일정을 iCalendar (.ics) 파일로 반환.

    캐시에서 공고를 찾아 접수 기간 + 추정 당첨발표/계약 일정을 담은 ICS 생성.
    구글 캘린더, 아이폰 캘린더, 아웃룩 등에서 바로 임포트 가능.
    """
    ann = _resolve_ann_from_cache(ann_id)
    if not ann:
        raise HTTPException(
            status_code=404,
            detail=f"공고 {ann_id}이 캐시에 없습니다. 먼저 /v1/apt/announcements로 조회 후 재시도하세요.",
        )

    ics_text = _build_ics(ann)
    return Response(
        content=ics_text.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{ann_id}.ics"'},
    )


def _build_ics(ann: dict) -> str:
    """공고 딕셔너리 → ICS 문자열 (라이브러리 의존 없이 직접 생성)."""
    from datetime import datetime, timedelta

    def _clean(s: str) -> str:
        return s.replace(",", r"\,").replace(";", r"\;").replace("\n", r"\n")

    def _parse_date(s: str) -> str | None:
        """YYYYMMDD 또는 YYYY-MM-DD → YYYYMMDD. 실패 시 None."""
        if not s:
            return None
        s = s.strip().replace("-", "")
        if len(s) >= 8 and s[:8].isdigit():
            return s[:8]
        return None

    now_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    uid_base = f"{ann.get('id', 'unknown')}@k-apt-alert"
    name = _clean(ann.get("name", "청약 공고"))
    url = ann.get("url", "")
    period = ann.get("period", "")
    rcept_end_raw = ann.get("rcept_end", "")

    # 접수 기간 파싱
    start_dt = end_dt = None
    if "~" in period:
        parts = period.split("~")
        start_dt = _parse_date(parts[0].strip())
        end_dt = _parse_date(parts[1].strip())
    if not end_dt:
        end_dt = _parse_date(rcept_end_raw)
    if not start_dt and end_dt:
        start_dt = end_dt

    events = []

    if start_dt and end_dt:
        # iCal DTEND는 exclusive → 마지막날 +1
        end_excl = (datetime.strptime(end_dt, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        desc = _clean(f"청약 접수 기간: {period}\nURL: {url}")
        events.append(
            f"BEGIN:VEVENT\r\n"
            f"UID:{uid_base}-rcept\r\n"
            f"DTSTAMP:{now_utc}\r\n"
            f"DTSTART;VALUE=DATE:{start_dt}\r\n"
            f"DTEND;VALUE=DATE:{end_excl}\r\n"
            f"SUMMARY:청약접수: {name}\r\n"
            f"DESCRIPTION:{desc}\r\n"
            f"END:VEVENT"
        )

        # 추정 당첨자 발표 (접수 마감 후 7~10일)
        winner_dt = (datetime.strptime(end_dt, "%Y%m%d") + timedelta(days=8)).strftime("%Y%m%d")
        winner_end = (datetime.strptime(end_dt, "%Y%m%d") + timedelta(days=9)).strftime("%Y%m%d")
        events.append(
            f"BEGIN:VEVENT\r\n"
            f"UID:{uid_base}-winner\r\n"
            f"DTSTAMP:{now_utc}\r\n"
            f"DTSTART;VALUE=DATE:{winner_dt}\r\n"
            f"DTEND;VALUE=DATE:{winner_end}\r\n"
            f"SUMMARY:[추정]당첨발표: {name}\r\n"
            f"DESCRIPTION:추정 당첨자 발표일 (마감 후 7-10일 기준). 실제 날짜는 공고문 확인.\r\n"
            f"END:VEVENT"
        )

        # 추정 계약 (당첨 발표 후 약 2주)
        contract_dt = (datetime.strptime(end_dt, "%Y%m%d") + timedelta(days=21)).strftime("%Y%m%d")
        contract_end = (datetime.strptime(end_dt, "%Y%m%d") + timedelta(days=25)).strftime("%Y%m%d")
        events.append(
            f"BEGIN:VEVENT\r\n"
            f"UID:{uid_base}-contract\r\n"
            f"DTSTAMP:{now_utc}\r\n"
            f"DTSTART;VALUE=DATE:{contract_dt}\r\n"
            f"DTEND;VALUE=DATE:{contract_end}\r\n"
            f"SUMMARY:[추정]계약: {name}\r\n"
            f"DESCRIPTION:추정 계약 기간 (당첨 발표 후 약 1-2주 기준). 실제 날짜는 공고문 확인.\r\n"
            f"END:VEVENT"
        )

    cal_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//k-apt-alert//청약알리미//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        *events,
        "END:VCALENDAR",
    ]
    return "\r\n".join(cal_lines)


@app.get("/v1/apt/announcements/{ann_id}/competition")
def get_competition_estimate(ann_id: str, history: bool = False):
    """공고의 경쟁률·커트라인 조회.

    1순위: 청약홈 당첨자 발표 결과 HTML (접수 마감+결과 발표 공고)
    2순위: 공공데이터포털 결과 API 기반 지역 과거 이력 (history=true)
    3순위: 2024-2025년 통계 기반 추정치 (fallback)
    """
    ann = _resolve_ann_from_cache(ann_id)
    if not ann:
        raise HTTPException(
            status_code=404,
            detail=f"공고 {ann_id}이 캐시에 없습니다. 먼저 /v1/apt/announcements로 조회 후 재시도하세요.",
        )

    # ann_id에서 pblanc_no 추출 (예: "apt_2026000123" → "2026000123")
    pblanc_no = ann_id.split("_", 1)[-1] if "_" in ann_id else ann_id

    base = {
        "id": ann_id,
        "name": ann.get("name"),
        "region": ann.get("region"),
        "size": ann.get("size"),
        "speculative_zone": ann.get("speculative_zone"),
    }

    # 1순위: 청약홈 실제 결과 페이지
    real = competition_crawler.fetch_result(pblanc_no)
    if real:
        return {**base, **real}

    # 2순위: 지역 과거 이력 (history=true 요청 시)
    if history:
        region = ann.get("region", "")
        past = competition_crawler.fetch_regional_history(region, months_back=12)
        if past:
            sorted_past = sorted(
                past, key=lambda p: p.get("rcept_end", ""), reverse=True
            )
            most_recent = sorted_past[0]

            rates = [p["competition_rate"] for p in past if p.get("competition_rate")]
            cutoffs = [p["cutoff_avg"] for p in past if p.get("cutoff_avg")]
            avg_rate = round(sum(rates) / len(rates), 1) if rates else None
            avg_cutoff = round(sum(cutoffs) / len(cutoffs), 1) if cutoffs else None

            return {
                **base,
                "source": "regional_history",
                "most_recent": {
                    "name": most_recent.get("name"),
                    "rcept_end": most_recent.get("rcept_end"),
                    "competition_rate": most_recent.get("competition_rate"),
                    "cutoff_avg": most_recent.get("cutoff_avg"),
                },
                "avg_rate": avg_rate,
                "avg_cutoff_score": avg_cutoff,
                "history_count": len(past),
                "history": sorted_past[:10],
                "disclaimer": (
                    f"{region} 최근 12개월 실제 청약 결과 {len(past)}건 기준. "
                    "공고별 단지·입지 차이로 실제 경쟁률은 크게 다를 수 있습니다."
                ),
            }

    # 3순위: 통계 기반 추정 폴백
    estimate = scoring.estimate_competition(ann)
    estimate["data_type"] = "통계 추정치"
    estimate["disclaimer"] = (
        "[통계 추정치] " + estimate.get("disclaimer", "")
        + " 과거 유사 단지 기준 참고치이며 실제와 다를 수 있습니다."
    )
    return {**base, **estimate}


def _resolve_ann_from_cache(ann_id: str) -> dict | None:
    """캐시 전체 스캔으로 ann_id 일치 공고 반환."""
    with _cache_lock:
        for entry in _cache.values():
            for item in entry.get("items", []):
                if item.get("id") == ann_id:
                    return item
    return None


@app.get("/v1/apt/changes")
def get_changes(
    since: str = Query(default="", description="이 날짜 이후 변경만 (YYYY-MM-DD)"),
    change_type: str = Query(default="", description="필터: new / updated / removed"),
    limit: int = Query(default=50, ge=1, le=200),
    force_refresh: bool = Query(default=False, description="raw URL 캐시 무시"),
):
    """공고 변동 이력 조회.

    GitHub Actions가 매일 KST 08:00 갱신한 changes.json을 반환합니다.
    `since`로 날짜 컷 / `change_type`으로 종류 필터링.

    응답 예:
        {
          "changes": [
            {"id": "...", "type": "new", "detected_at": "2026-05-06", "name": "...", ...},
            {"id": "...", "type": "updated", "field_changes": {"period": {"before": "...", "after": "..."}}}
          ],
          "count": N,
          "updated_at": "2026-05-06T23:00:00Z",
          "retention_days": 30,
          "status": "ok" | "not_yet_initialized"
        }
    """
    if change_type and change_type not in ("new", "updated", "removed"):
        raise HTTPException(
            status_code=400,
            detail="change_type must be one of: new, updated, removed",
        )

    try:
        log = changes_store.get_log(force_refresh=force_refresh)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"changes.json fetch failed: {e}")

    items = changes_store.filter_changes(log, since=since, change_type=change_type, limit=limit)
    return {
        "changes": items,
        "count": len(items),
        "updated_at": log.get("updated_at", ""),
        "retention_days": log.get("retention_days", 30),
        "tracking_status": log.get("tracking_status", "ready"),
        "first_diff_date": log.get("first_diff_date"),
        "status": log.get("_status", "ok"),
    }


@app.get("/v1/apt/changes/cache-status")
def changes_cache_status():
    """디버그용 — 변동 추적 캐시 상태."""
    return changes_store.cache_status()


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
            {"id": "sh", "name": "SH 공공주택", "description": "서울주택도시공사 — 장기전세·청년안심·매입임대 등"},
            {"id": "gh", "name": "GH 공공주택", "description": "경기주택도시공사 — 경기행복주택·매입임대 등"},
        ]
    }


# ─────────────────────────────────────────────────────────────────
# notice-raw — 모집공고 본문 추출 (Phase 1 of notice-interpreter)
# ─────────────────────────────────────────────────────────────────

_notice_raw_counter = {"date": "", "count": 0}
_notice_raw_lock = Lock()


def _notice_raw_check_limit() -> tuple[int, int]:
    today = datetime.now().strftime("%Y-%m-%d")
    with _notice_raw_lock:
        if _notice_raw_counter["date"] != today:
            _notice_raw_counter["date"] = today
            _notice_raw_counter["count"] = 0
        _notice_raw_counter["count"] += 1
        return _notice_raw_counter["count"], NOTICE_RAW_DAILY_LIMIT_FREE


def _resolve_tier(authorization: str | None) -> str:
    """Phase 1 스텁 — 토큰 무관하게 free. Phase 2에서 Supabase JWT 검증."""
    return "free"


def _resolve_url_from_cache(notice_id: str) -> str | None:
    """_cache (announcements 인메모리 캐시) 전체 카테고리에서 id 매칭."""
    with _cache_lock:
        for entry in _cache.values():
            for ann in entry.get("items", []):
                if ann.get("id") == notice_id:
                    return ann.get("url", "")
    return None


def _resolve_ann_meta_from_cache(notice_id: str) -> tuple[str, str]:
    """캐시에서 (url, name) 동시 반환. 없으면 ('', '')."""
    with _cache_lock:
        for entry in _cache.values():
            for ann in entry.get("items", []):
                if ann.get("id") == notice_id:
                    return ann.get("url", "") or "", ann.get("name", "") or ""
    return "", ""


@app.get("/v1/apt/notice/{notice_id}/raw")
def get_notice_raw(
    notice_id: str,
    url: str = Query(default="", description="id 캐시 매칭 실패 시 직접 전달할 공고 URL"),
    max_chars: int = Query(
        default=NOTICE_MAX_CHARS_DEFAULT,
        ge=1000,
        le=TIER_LIMITS["paid"],
        description="응답 텍스트 상한 (free 30000 cap, paid 80000 cap)",
    ),
    tier: str = Query(default="free", description="요청 티어 — free | paid (paid는 인증 필요)"),
    force_refresh: bool = Query(default=False, description="캐시 무시하고 재수집"),
    authorization: str | None = None,
):
    """모집공고 본문 텍스트 추출 — LLM 요약 입력용.

    - id로 캐시에서 url 조회 (A안), 실패 시 ?url= 폴백 (C안)
    - 호스트는 화이트리스트 검증 (applyhome.co.kr / apply.lh.or.kr / i-sh.co.kr / gh.or.kr)
    - 무료 30K, 유료 80K (Phase 1은 무료 강제)
    - 7일 캐시, force_refresh=true로 무효화
    """
    effective_tier = _resolve_tier(authorization)
    cap = TIER_LIMITS[effective_tier]
    effective_max_chars = min(max_chars, cap)
    tier_capped = max_chars > cap

    if effective_tier == "free":
        count, limit = _notice_raw_check_limit()
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail=f"Daily notice_raw limit exceeded ({limit}). Upgrade to paid tier.",
            )

    cached_url, cached_name = _resolve_ann_meta_from_cache(notice_id)
    resolved_url = cached_url or url
    if not resolved_url:
        raise HTTPException(
            status_code=404,
            detail=(
                f"id '{notice_id}' not in announcements cache. "
                "Provide ?url=<applyhome_url|lh_url> as fallback."
            ),
        )

    if not is_supported_host(resolved_url):
        raise HTTPException(
            status_code=400,
            detail=(
                f"unsupported host. Phase 1 supports applyhome.co.kr, apply.lh.or.kr, "
                f"i-sh.co.kr, gh.or.kr only. Got: {resolved_url}"
            ),
        )

    if force_refresh:
        notice_raw_invalidate(notice_id)

    try:
        result = extract_notice_raw(
            notice_id=notice_id,
            url=resolved_url,
            max_chars=effective_max_chars,
            force_refresh=force_refresh,
            fallback_title=cached_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"notice_raw extract failed: {e}")

    result["tier"] = effective_tier
    result["effective_max_chars"] = effective_max_chars
    result["tier_capped"] = tier_capped
    return result


@app.get("/v1/apt/notice/cache-status")
def notice_raw_cache_status_endpoint():
    """디버그용 — notice_raw 캐시 상태."""
    with _notice_raw_lock:
        rate = {
            "date": _notice_raw_counter["date"],
            "count": _notice_raw_counter["count"],
            "limit_free": NOTICE_RAW_DAILY_LIMIT_FREE,
        }
    return {
        "cache": notice_raw_cache_status(),
        "rate_limit": rate,
        "tier_limits": TIER_LIMITS,
    }
