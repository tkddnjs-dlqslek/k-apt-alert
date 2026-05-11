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
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path
from threading import Lock
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

try:
    import cloudscraper
    _SCRAPER = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    _SCRAPER = None
    CLOUDSCRAPER_AVAILABLE = False

from config import (
    NOTICE_RAW_HTTP_TIMEOUT,
    NOTICE_RAW_TTL,
    NOTICE_SUPPORTED_HOSTS,
)

logger = logging.getLogger(__name__)

# PDF 다운로드·파싱 타임아웃·상한
PDF_HTTP_TIMEOUT = 30
PDF_MAX_SIZE_MB = 30
PDF_MAX_PAGES = 50  # 추출 페이지 상한 (큰 PDF 메모리 보호)

# kordoc CLI (HWP/HWPX) 호출 타임아웃
HWP_CONVERT_TIMEOUT = 120

# 첨부파일 매직 바이트 시그니처
_MAGIC_PDF = b"%PDF"
_MAGIC_HWP_CFB = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # OLE2/CFB (HWP 5.0)
_MAGIC_HWPX = b"PK\x03\x04"  # ZIP (HWPX or DOCX/XLSX)


def _detect_attachment_type(data: bytes) -> str:
    """첨부파일 매직 바이트로 종류 판정 (pdf / hwp / hwpx / unknown)."""
    head = data[:8]
    if head.startswith(_MAGIC_PDF):
        return "pdf"
    if head.startswith(_MAGIC_HWP_CFB):
        return "hwp"
    if head.startswith(_MAGIC_HWPX):
        # HWPX·DOCX·XLSX·ZIP 공통 헤더. kordoc은 HWPX·DOCX·XLSX 모두 지원.
        return "hwpx"
    return "unknown"

_cache: dict = {}
_cache_lock = Lock()

# 섹션 헤딩 패턴 — 청약홈/LH/SH/GH 공통적으로 자주 등장. 매칭되면 sections dict에 split.
# 주의: "공급대상"은 자격 요건 텍스트가 아니라 주택형/세대수 표라서 "자격"과 분리한다.
# "자격" 섹션은 사용자가 "내 신청 자격"을 물을 때 답변용이므로, 표가 아닌 텍스트만 잡는다.
_SECTION_PATTERNS = [
    ("공급대상", re.compile(r"공급\s*대상")),
    ("자격", re.compile(
        r"(?:신청\s*자격|입주자\s*자격|자격\s*요건|자격\s*조건|청약\s*자격|"
        r"신청\s*자\s*격|1순위\s*자격|무주택\s*세대\s*구성원\s*확인|입주\s*자격)"
    )),
    ("공급일정", re.compile(
        r"(?:공급\s*일정|모집\s*일정|청약\s*일정|접수\s*일정|청약\s*접수|"
        r"당첨자\s*발표|일정\s*안내|입주자\s*모집\s*공고일)"
    )),
    ("공급금액", re.compile(
        r"(?:공급\s*(?:금액|가격|가)|분양\s*가(?:격)?|임대\s*보증금|임대료|"
        r"공급\s*조건|매매가|월\s*임대료)"
    )),
    ("유의사항", re.compile(
        r"(?:유의\s*사항|주의\s*사항|참고\s*사항|기타\s*사항|안내\s*사항|"
        r"알려\s*드립니다|꼭\s*확인|당부\s*말씀)"
    )),
]

# 사이트 공통 제너릭 타이틀 — 이 값이면 fallback_title 사용
_GENERIC_TITLES = {
    "청약홈", "청약Home", "applyhome", "LH한국토지주택공사", "LH 한국토지주택공사",
    "LH 청약플러스", "LH청약플러스", "SH서울주택도시공사", "SH 서울주택도시공사",
    "GH경기주택도시공사", "GH 경기주택도시공사", "경기주택도시공사",
}


def _smart_fetch(url: str, timeout: int = 30) -> requests.Response:
    """봇 차단 우회를 위해 cloudscraper 우선 시도, 실패·미설치 시 requests fallback.

    GH 같은 사이트가 Render IP에서 1.3KB 빈 페이지만 반환하는 케이스 대응.
    응답이 너무 작으면 (<5KB) 차단으로 간주하고 다른 방법으로 재시도.
    """
    # Try 1: cloudscraper if available
    if CLOUDSCRAPER_AVAILABLE and _SCRAPER is not None:
        try:
            resp = _SCRAPER.get(url, timeout=timeout, headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            })
            if resp.status_code == 200 and len(resp.content) > 5000:
                logger.info(f"[fetch] cloudscraper OK ({len(resp.content)} bytes) {url[:80]}")
                return resp
            logger.info(f"[fetch] cloudscraper response small ({len(resp.content)}b), try requests")
        except Exception as e:
            logger.info(f"[fetch] cloudscraper failed: {e}, try requests")

    # Try 2: regular requests with browser headers
    resp = requests.get(url, timeout=timeout, headers=_BROWSER_HEADERS)
    if resp.status_code == 200 and len(resp.content) < 5000:
        logger.warning(f"[fetch] suspiciously small response ({len(resp.content)}b) — bot block?")
    return resp


def _find_pdf_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """페이지에서 첨부 다운로드 URL 추출 (PDF·HWP 무관, 일단 후보로).

    사이트별 패턴:
    - 직접 .pdf 링크
    - GH: `?mode=download&articleNo=X&attachNo=Y` (텍스트 "다운로드")
    - SH: `filedown.do?...` 또는 `atchFileDownload`
    - 일반: `/download`, `filedownload`, `attach`

    실제 PDF 여부는 _extract_pdf_text()의 Content-Type 검사 + pdfplumber 시도로 확정.
    """
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        href_lower = href.lower()

        # 1. 직접 .pdf 링크
        if href_lower.endswith(".pdf") or ".pdf?" in href_lower:
            candidates.append(urljoin(base_url, href))
            continue

        # 2. 다운로드 패턴 매칭 (URL)
        download_patterns = (
            "filedown", "filedownload", "atchfile", "attach", "download",
            "mode=download", "fileno", "atchnno",
        )
        if any(p in href_lower for p in download_patterns):
            # URL에 명백한 다운로드 신호 있으면 텍스트 무관 통과
            candidates.append(urljoin(base_url, href))

    # 중복 제거 (순서 보존)
    seen = set()
    unique = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique[:5]  # 최대 5개까지만


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_BROWSER_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _download_attachment(url: str) -> bytes | None:
    """첨부파일 다운로드 (cloudscraper 우선, fallback requests)."""
    headers = {**_BROWSER_HEADERS, "Accept": "*/*"}
    try:
        if CLOUDSCRAPER_AVAILABLE and _SCRAPER is not None:
            try:
                resp = _SCRAPER.get(url, timeout=PDF_HTTP_TIMEOUT,
                                     headers={"Accept": "*/*"}, allow_redirects=True)
            except Exception:
                resp = requests.get(url, timeout=PDF_HTTP_TIMEOUT,
                                     headers=headers, allow_redirects=True)
        else:
            resp = requests.get(url, timeout=PDF_HTTP_TIMEOUT,
                                 headers=headers, allow_redirects=True)
        resp.raise_for_status()
        if len(resp.content) > PDF_MAX_SIZE_MB * 1024 * 1024:
            logger.warning(f"[attach] {url} too large, skip")
            return None
        return resp.content
    except requests.RequestException as e:
        logger.warning(f"[attach] {url} fetch failed: {e}")
        return None


def _extract_pdf_bytes(data: bytes) -> tuple[str, int] | None:
    """PDF bytes → (텍스트, 페이지 수). pdfplumber 사용."""
    if not PDFPLUMBER_AVAILABLE:
        return None
    try:
        parts = []
        with pdfplumber.open(BytesIO(data)) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages[:PDF_MAX_PAGES]):
                txt = page.extract_text() or ""
                if txt.strip():
                    parts.append(f"\n--- [PDF page {i + 1}] ---\n{txt}")
        text = "\n".join(parts).strip()
        if not text:
            return None
        return text, page_count
    except Exception as e:
        logger.warning(f"[pdf] extract failed: {e}")
        return None


def _extract_hwp_bytes(data: bytes, suffix: str = ".hwp") -> tuple[str, int] | None:
    """HWP/HWPX bytes → (Markdown 텍스트, 1). kordoc CLI 호출."""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["kordoc", tmp_path],
                capture_output=True,
                timeout=HWP_CONVERT_TIMEOUT,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="ignore")[:200]
                logger.warning(f"[hwp] kordoc returncode={result.returncode}: {stderr}")
                return None
            text = result.stdout.decode("utf-8", errors="ignore").strip()
            if not text:
                logger.info("[hwp] kordoc extracted 0 text")
                return None
            return text, 1
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
    except FileNotFoundError:
        logger.warning("[hwp] kordoc CLI not installed — skip")
        return None
    except subprocess.TimeoutExpired:
        logger.warning(f"[hwp] kordoc timeout after {HWP_CONVERT_TIMEOUT}s")
        return None
    except Exception as e:
        logger.warning(f"[hwp] extract failed: {e}")
        return None


def _extract_attachment_text(url: str) -> tuple[str, int, str] | None:
    """다운로드 URL → (텍스트, 페이지 수, 유형). 유형: 'pdf' | 'hwp' | 'hwpx'.

    매직 바이트로 자동 판별 → 적절한 추출기 호출.
    """
    data = _download_attachment(url)
    if not data:
        return None
    kind = _detect_attachment_type(data)
    if kind == "pdf":
        result = _extract_pdf_bytes(data)
        if result:
            return result[0], result[1], "pdf"
    elif kind == "hwp":
        result = _extract_hwp_bytes(data, suffix=".hwp")
        if result:
            return result[0], result[1], "hwp"
    elif kind == "hwpx":
        # ZIP-based — HWPX·DOCX·XLSX 가능성. kordoc은 모두 지원.
        result = _extract_hwp_bytes(data, suffix=".hwpx")
        if result:
            return result[0], result[1], "hwpx"
    else:
        logger.info(f"[attach] {url} unknown type (magic={data[:8]!r})")
    return None

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


# SH/LH/GH 페이지에 자주 나오는 카테고리·메뉴 단어 — 공고명으로 부적합
_GENERIC_NAV_PATTERNS = re.compile(
    r"^(주택임대|공공임대|분양|공지사항|보도자료|입주자\s*모집|공고|HOME|메뉴|로그인|"
    r"청약일정|회원가입|마이페이지|장기전세|행복주택|매입임대|국민임대)$"
)

_MIN_TITLE_LEN = 10  # 의미 있는 공고명 최소 길이


def _is_generic_title(title: str) -> bool:
    """페이지 <title>이 사이트 브랜드명 또는 메뉴 수준이라 공고명으로 못 쓸 때 True."""
    if not title:
        return True
    norm = title.strip()
    if norm in _GENERIC_TITLES:
        return True
    if _GENERIC_NAV_PATTERNS.match(norm):
        return True
    # "청약홈 - ..." 식으로 brand prefix만 있으면 generic 처리
    if any(norm == g or norm.startswith(f"{g} -") or norm.startswith(f"{g}|") for g in _GENERIC_TITLES):
        return True
    return False


def _extract_title(soup: BeautifulSoup, fallback: str = "") -> str:
    """공고명 추출 전략:
    1) fallback이 충분한 길이로 주어졌다면 그것을 신뢰 (announcement.name이 공식 정보)
    2) fallback 짧거나 없으면 본문 h1/h2/.title 중 generic 아닌 첫 후보
    3) 마지막으로 <title> 검사 (대부분 사이트명)
    """
    if fallback and len(fallback.strip()) >= _MIN_TITLE_LEN:
        # API가 준 공식 공고명을 우선 — 페이지 메뉴/카테고리명에 흔들리지 않음
        return fallback.strip()[:200]

    for sel in ("h1", "h2", ".title", ".tit", ".board_tit", ".board-tit", ".view_tit", ".view-tit"):
        tag = soup.select_one(sel)
        if tag:
            txt = tag.get_text(strip=True)
            if txt and not _is_generic_title(txt) and len(txt) >= _MIN_TITLE_LEN:
                return txt[:200]

    title_tag = soup.find("title")
    if title_tag:
        txt = title_tag.text.strip()
        if txt and not _is_generic_title(txt) and len(txt) >= _MIN_TITLE_LEN:
            return txt[:200]

    return fallback or ""


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


def _extract_sh(html: str, fallback_title: str = "", page_url: str = "") -> dict:
    """SH (i-sh.co.kr) 게시판 view.do 상세 페이지 + 첨부 PDF 통합 추출."""
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup, fallback=fallback_title)

    container = soup.select_one(
        ".board_view, .board-view, .view_cont, .view-cont, .bbs_view, .bbs-view, "
        ".cont_view, .cont-view, .board_cont, .board-cont, #content"
    )
    if not container:
        container = soup.body or soup

    html_text = _clean_text(BeautifulSoup(str(container), "html.parser"))
    return _augment_with_attachments(soup, html_text, title, page_url)


def _extract_gh(html: str, fallback_title: str = "", page_url: str = "") -> dict:
    """GH (gh.or.kr) announcement-of-salerental001.do 상세 페이지 + 첨부 HWP/PDF 통합 추출."""
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup, fallback=fallback_title)

    container = soup.select_one(
        ".board_view, .board-view, .view_content, .view-content, .bbs_view, .bbs-view, "
        ".table_view, .table-view, .view_cont, .view-cont, .content_view, .content-view, #content"
    )
    if not container:
        container = soup.body or soup

    html_text = _clean_text(BeautifulSoup(str(container), "html.parser"))
    return _augment_with_attachments(soup, html_text, title, page_url)


def _augment_with_attachments(soup: BeautifulSoup, html_text: str, title: str, page_url: str) -> dict:
    """GH/SH 페이지 본문에 첨부파일(PDF·HWP·HWPX) 텍스트를 합쳐 반환.

    첨부가 없거나 추출 실패해도 HTML 본문은 그대로 반환 (graceful degradation).
    """
    urls = _find_pdf_links(soup, page_url) if page_url else []
    parts = []
    pages_total = 0
    fetched = 0
    kinds: list[str] = []

    for url in urls:
        result = _extract_attachment_text(url)
        if result:
            text, pages, kind = result
            label = "PDF" if kind == "pdf" else "HWP" if kind == "hwp" else "HWPX"
            parts.append(f"\n=== 첨부 {label} 본문 ===\n{text}")
            pages_total += pages
            fetched += 1
            kinds.append(kind)

    combined = html_text + ("\n\n" + "\n\n".join(parts) if parts else "")

    return {
        "title": title,
        "text": combined,
        "has_pdf": "pdf" in kinds,
        "has_hwp": "hwp" in kinds or "hwpx" in kinds,
        "attachment_kinds": kinds,
        "pdf_pages": pages_total,
        "pdf_count": fetched,
    }


# Backwards-compat alias (deprecated)
_augment_with_pdf = _augment_with_attachments


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
        resp = _smart_fetch(url, timeout=NOTICE_RAW_HTTP_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"fetch failed: {e}")

    try:
        # GH/SH는 PDF 첨부 추출 위해 page_url도 전달, 나머지는 무시
        if extractor in (_extract_gh, _extract_sh):
            extracted = extractor(resp.text, fallback_title=fallback_title, page_url=url)
        else:
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
        "has_pdf": extracted.get("has_pdf", False),
        "has_hwp": extracted.get("has_hwp", False),
        "attachment_kinds": extracted.get("attachment_kinds", []),
        "pdf_pages": extracted.get("pdf_pages", 0),
        "pdf_count": extracted.get("pdf_count", 0),
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
        "has_pdf": full_data.get("has_pdf", False),
        "has_hwp": full_data.get("has_hwp", False),
        "attachment_kinds": full_data.get("attachment_kinds", []),
        "pdf_pages": full_data.get("pdf_pages", 0),
        "pdf_count": full_data.get("pdf_count", 0),
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
