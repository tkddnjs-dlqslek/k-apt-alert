"""모집공고 raw 텍스트 추출기 (Phase 1).

청약홈(applyhome.co.kr) + LH(apply.lh.or.kr) + SH(i-sh.co.kr) + GH(gh.or.kr)
공고 상세 페이지의 본문 텍스트를 정규화하여 반환한다.
LLM이 사용자 프로필 컨텍스트로 요약·해석하기 위한 입력.

핵심:
- 호스트별 dispatcher
- 7일 TTL 캐시 (id 키, force_refresh로 무효화 가능)
- 섹션 헤딩 감지 (자격/일정/금액/유의사항)
- max_chars truncation
"""

import logging
import re
import time
from threading import Lock
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import (
    NOTICE_RAW_HTTP_TIMEOUT,
    NOTICE_RAW_TTL,
    NOTICE_SUPPORTED_HOSTS,
)

logger = logging.getLogger(__name__)

_cache: dict = {}
_cache_lock = Lock()

# 섹션 헤딩 패턴 — 청약홈/LH 공통적으로 자주 등장. 매칭되면 sections dict에 split.
# 주의: "공급대상"은 자격 요건 텍스트가 아니라 주택형/세대수 표라서 "자격"과 분리한다.
# "자격" 섹션은 사용자가 "내 신청 자격"을 물을 때 답변용이므로, 표가 아닌 텍스트만 잡는다.
_SECTION_PATTERNS = [
    ("공급대상", re.compile(r"공급\s*대상")),
    ("자격", re.compile(r"(?:신청\s*자격|입주자\s*자격|자격\s*요건|청약\s*자격)")),
    ("공급일정", re.compile(r"(?:공급\s*일정|모집\s*일정|청약\s*일정|접수\s*일정)")),
    ("공급금액", re.compile(r"(?:공급\s*(?:금액|가격)|분양\s*가|임대\s*보증금|공급\s*조건)")),
    ("유의사항", re.compile(r"(?:유의\s*사항|주의\s*사항|참고\s*사항|기타\s*사항)")),
]

# 사이트 공통 제너릭 타이틀 — 이 값이면 fallback_title 사용
_GENERIC_TITLES = {
    "청약홈", "청약Home", "applyhome", "LH한국토지주택공사", "LH 한국토지주택공사",
    "LH 청약플러스", "LH청약플러스", "SH서울주택도시공사", "SH 서울주택도시공사",
    "GH경기주택도시공사", "GH 경기주택도시공사", "경기주택도시공사",
}

# 노이즈 패턴 — 본문 정규화 시 제거
_WHITESPACE_RE = re.compile(r"[ \t]+")
_NEWLINE_RE = re.compile(r"\n{3,}")


def is_supported_host(url: str) -> bool:
    """SSRF 방지 — 화이트리스트된 호스트만 허용."""
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
        return any(allowed in host for allowed in NOTICE_SUPPORTED_HOSTS)
    except Exception:
        return False


def _clean_text(soup: BeautifulSoup) -> str:
    """script/style/nav/footer 제거 + 텍스트 추출 + 공백 정규화."""
    for tag in soup(["script", "style", "nav", "footer", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _detect_sections(text: str) -> dict:
    """본문 텍스트에서 섹션 헤딩 위치를 감지하여 dict로 분할.

    같은 라벨이 본문에 여러 번 등장(헤딩 + 본문 중 재언급)할 수 있어,
    먼저 라벨별 첫 등장 위치만 남겨 경계를 계산한다 — 그래야 두 번째 등장이
    다음 섹션 경계로 오인되지 않는다.
    """
    hits = []
    for label, pattern in _SECTION_PATTERNS:
        for m in pattern.finditer(text):
            hits.append((m.start(), label))
    if not hits:
        return {}
    hits.sort(key=lambda x: x[0])

    # 라벨별 첫 등장만 유지 (소스 순서)
    seen = set()
    unique_hits = []
    for pos, label in hits:
        if label not in seen:
            seen.add(label)
            unique_hits.append((pos, label))

    sections: dict = {}
    for i, (start, label) in enumerate(unique_hits):
        end = unique_hits[i + 1][0] if i + 1 < len(unique_hits) else len(text)
        sections[label] = text[start:end].strip()[:5000]  # 섹션당 5KB 상한
    return sections


def _is_generic_title(title: str) -> bool:
    """페이지 <title>이 사이트 브랜드명 수준이라 공고명으로 못 쓸 때 True."""
    if not title:
        return True
    norm = title.strip()
    if norm in _GENERIC_TITLES:
        return True
    # "청약홈 - ..." 식으로 brand prefix만 있으면 generic 처리
    return any(norm == g or norm.startswith(f"{g} -") or norm.startswith(f"{g}|") for g in _GENERIC_TITLES)


def _extract_title(soup: BeautifulSoup, fallback: str = "") -> str:
    """공고명 추출 — h1/h2 우선, 그다음 <title>, generic이면 fallback."""
    # 청약홈 등은 본문 안에 실제 공고명이 h1/h2/.title로 들어 있다
    for sel in ("h1", "h2", ".title", ".tit", ".board_tit", ".board-tit", ".view_tit", ".view-tit"):
        tag = soup.select_one(sel)
        if tag:
            txt = tag.get_text(strip=True)
            if txt and not _is_generic_title(txt) and len(txt) > 3:
                return txt[:200]

    title_tag = soup.find("title")
    if title_tag:
        txt = title_tag.text.strip()
        if txt and not _is_generic_title(txt):
            return txt[:200]

    return fallback


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n\n[... truncated]", True


def _extract_applyhome(html: str, fallback_title: str = "") -> dict:
    """청약홈 SSR 페이지 추출. 본문 컨테이너 선호도: .cont > #pblancCont > body."""
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup, fallback=fallback_title)

    container = soup.select_one(".cont, #pblancCont, .pblanc_cont, .board-view, .view-cont")
    if not container:
        container = soup.body or soup

    text = _clean_text(BeautifulSoup(str(container), "html.parser"))
    return {"title": title, "text": text}


def _extract_lh(html: str, fallback_title: str = "") -> dict:
    """LH apply.lh.or.kr 게시글 상세 페이지 추출."""
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup, fallback=fallback_title)

    container = soup.select_one(
        ".board-view, .view-content, .view-cont, #content, .bbs-view, .cont-area"
    )
    if not container:
        container = soup.body or soup

    text = _clean_text(BeautifulSoup(str(container), "html.parser"))
    return {"title": title, "text": text}


def _extract_sh(html: str, fallback_title: str = "") -> dict:
    """SH (i-sh.co.kr) 게시판 view.do 상세 페이지 추출."""
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup, fallback=fallback_title)

    container = soup.select_one(
        ".board_view, .board-view, .view_cont, .view-cont, .bbs_view, .bbs-view, "
        ".cont_view, .cont-view, .board_cont, .board-cont, #content"
    )
    if not container:
        container = soup.body or soup

    text = _clean_text(BeautifulSoup(str(container), "html.parser"))
    return {"title": title, "text": text}


def _extract_gh(html: str, fallback_title: str = "") -> dict:
    """GH (gh.or.kr) announcement-of-salerental001.do 상세 페이지 추출."""
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup, fallback=fallback_title)

    container = soup.select_one(
        ".board_view, .board-view, .view_content, .view-content, .bbs_view, .bbs-view, "
        ".table_view, .table-view, .view_cont, .view-cont, .content_view, .content-view, #content"
    )
    if not container:
        container = soup.body or soup

    text = _clean_text(BeautifulSoup(str(container), "html.parser"))
    return {"title": title, "text": text}


_EXTRACTORS = (
    ("applyhome.co.kr", _extract_applyhome),
    ("apply.lh.or.kr", _extract_lh),
    ("i-sh.co.kr", _extract_sh),
    ("gh.or.kr", _extract_gh),
)


def _pick_extractor(url: str):
    host = urlparse(url).netloc.lower()
    for needle, fn in _EXTRACTORS:
        if needle in host:
            return fn
    return None


def extract_notice_raw(
    notice_id: str,
    url: str,
    max_chars: int,
    force_refresh: bool = False,
    fallback_title: str = "",
) -> dict:
    """단일 공고의 raw 텍스트 추출. 7일 캐시 + max_chars truncation.

    Returns:
        {
            "id": str,
            "url": str,
            "source": "html",
            "title": str,
            "extracted_at": ISO8601,
            "char_count": int,
            "truncated": bool,
            "sections": dict[str, str],
            "text": str,
        }
    Raises:
        ValueError — unsupported host / fetch 실패 / 추출 실패
    """
    if not is_supported_host(url):
        raise ValueError(f"unsupported host for notice_raw: {url}")

    extractor = _pick_extractor(url)
    if extractor is None:
        raise ValueError(f"no extractor for url: {url}")

    now = time.time()

    if not force_refresh:
        with _cache_lock:
            entry = _cache.get(notice_id)
            if entry and now - entry["ts"] < NOTICE_RAW_TTL:
                logger.info(
                    f"[notice_raw] cache hit {notice_id} (age {int(now - entry['ts'])}s)"
                )
                return _build_response(entry["data"], max_chars, now)

    try:
        resp = requests.get(
            url,
            timeout=NOTICE_RAW_HTTP_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 k-apt-alert/3.0 (notice-interpreter)"},
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"fetch failed: {e}")

    try:
        extracted = extractor(resp.text, fallback_title=fallback_title)
    except Exception as e:
        raise ValueError(f"extract failed: {e}")

    text = extracted.get("text", "")
    if not text:
        raise ValueError("empty extracted text")

    sections = _detect_sections(text)

    full_data = {
        "id": notice_id,
        "url": url,
        "source": "html",
        "title": extracted.get("title", ""),
        "full_text": text,
        "sections": sections,
    }

    with _cache_lock:
        _cache[notice_id] = {"ts": now, "data": full_data}
    logger.info(
        f"[notice_raw] fetched {notice_id} ({len(text)} chars, {len(sections)} sections)"
    )

    return _build_response(full_data, max_chars, now)


def _build_response(full_data: dict, max_chars: int, now: float) -> dict:
    """캐시된 풀텍스트를 max_chars로 잘라 응답 구조 만든다."""
    truncated_text, was_truncated = _truncate(full_data["full_text"], max_chars)
    extracted_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
    return {
        "id": full_data["id"],
        "url": full_data["url"],
        "source": full_data["source"],
        "title": full_data["title"],
        "extracted_at": extracted_at,
        "char_count": len(truncated_text),
        "truncated": was_truncated,
        "sections": full_data["sections"],
        "text": truncated_text,
    }


def cache_status() -> dict:
    """디버그용 — 캐시 상태."""
    now = time.time()
    with _cache_lock:
        return {
            "count": len(_cache),
            "ttl_seconds": NOTICE_RAW_TTL,
            "samples": [
                {"id": k, "age_seconds": int(now - v["ts"]), "chars": len(v["data"]["full_text"])}
                for k, v in list(_cache.items())[:5]
            ],
        }


def invalidate(notice_id: str) -> bool:
    """force_refresh 또는 외부 트리거로 단일 캐시 무효화."""
    with _cache_lock:
        return _cache.pop(notice_id, None) is not None
