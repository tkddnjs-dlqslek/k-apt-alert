"""
k-apt-alert proxy server

공공데이터포털 청약 API를 프록시하여 사용자가 API 키 없이 청약 공고를 조회할 수 있게 합니다.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import DATA_GO_KR_API_KEY
from crawlers import applyhome, officetell, lh, remndr, pbl_pvt_rent, opt

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
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "api_key_configured": bool(DATA_GO_KR_API_KEY)}


@app.get("/v1/apt/announcements")
def get_all_announcements(
    category: str = Query(
        default="all",
        description="조회 카테고리: all, apt, officetell, lh, remndr, pbl_pvt_rent, opt",
    ),
    active_only: bool = Query(default=True, description="접수 마감 전 공고만"),
    months_back: int = Query(default=2, ge=1, le=12, description="조회 기간 (개월)"),
):
    """청약 공고 통합 조회. category로 특정 유형만 조회 가능."""
    if not DATA_GO_KR_API_KEY:
        raise HTTPException(status_code=503, detail="Server API key not configured")

    fetchers = {
        "apt": ("APT 일반분양", lambda: applyhome.fetch(months_back, active_only)),
        "officetell": ("오피스텔/도시형", lambda: officetell.fetch(min(months_back, 1), active_only)),
        "lh": ("LH 공공분양", lambda: lh.fetch(days_back=30 * months_back, active_only=active_only)),
        "remndr": ("APT 잔여세대", lambda: remndr.fetch(months_back, active_only)),
        "pbl_pvt_rent": ("공공지원민간임대", lambda: pbl_pvt_rent.fetch(min(months_back, 1), active_only)),
        "opt": ("임의공급", lambda: opt.fetch(min(months_back, 1), active_only)),
    }

    if category != "all" and category not in fetchers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Choose from: all, {', '.join(fetchers.keys())}",
        )

    targets = fetchers if category == "all" else {category: fetchers[category]}

    announcements = []
    errors = []

    for key, (label, fn) in targets.items():
        try:
            items = fn()
            logger.info(f"[{label}] {len(items)} items fetched")
            announcements.extend(items)
        except Exception as e:
            logger.error(f"[{label}] crawl failed: {e}")
            errors.append(f"{label}: {str(e)}")

    # ID 기준 전역 중복 제거
    seen = set()
    unique = []
    for ann in announcements:
        if ann["id"] not in seen:
            seen.add(ann["id"])
            unique.append(ann)

    return {
        "count": len(unique),
        "announcements": unique,
        "errors": errors if errors else None,
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
