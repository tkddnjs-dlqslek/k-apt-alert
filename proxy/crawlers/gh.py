"""경기주택도시공사(GH) 공고 크롤러.

공식 OpenAPI가 없어 HTML 스크래핑. 게시판 페이지의 주택 구분 공고만 추출.

페이지 구조 (gh.or.kr/gh/announcement-of-salerental001.do):
- table[0] row: 번호 / 구분 / 제목 / 부서 / 등록일(YY.MM.DD) / 조회수 / 첨부파일
- 제목 <a> href="?mode=view&articleNo=64782..."
"""

import logging
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

GH_LIST_URL = "https://www.gh.or.kr/gh/announcement-of-salerental001.do"
GH_DETAIL_URL_TEMPLATE = "https://www.gh.or.kr/gh/announcement-of-salerental001.do?mode=view&articleNo={article_no}"

# 제목 필터 (공고만 포함, 결과·발표 제외)
INCLUDE_KEYWORDS = ["모집공고", "분양공고", "공급공고", "입주자모집", "청약공고"]
EXCLUDE_KEYWORDS = ["결과", "발표", "당첨자", "계약대상", "선정", "취소", "변경안내"]

# 지역 추출용 (경기도 주요 지역)
GG_DISTRICTS = [
    "수원", "성남", "고양", "용인", "부천", "안산", "남양주", "안양", "화성", "평택",
    "의정부", "시흥", "파주", "김포", "광명", "광주", "군포", "오산", "이천", "양주",
    "구리", "안성", "포천", "의왕", "하남", "여주", "동두천", "과천", "가평", "양평",
]


def _parse_gh_row(row, today) -> dict | None:
    cells = row.find_all(["td"])
    if len(cells) < 6:
        return None

    category = cells[1].get_text(strip=True)
    if category != "주택":
        return None

    title_cell = cells[2]
    title = title_cell.get_text(strip=True)
    link = title_cell.find("a", href=True)
    if not link:
        return None

    # 제목 필터
    if not any(kw in title for kw in INCLUDE_KEYWORDS):
        return None
    if any(kw in title for kw in EXCLUDE_KEYWORDS):
        return None

    # articleNo 추출
    href = link["href"]
    m = re.search(r"articleNo=(\d+)", href)
    if not m:
        return None
    article_no = m.group(1)

    # 등록일 YY.MM.DD → YYYYMMDD
    reg_raw = cells[4].get_text(strip=True)
    reg_m = re.match(r"(\d{2})\.(\d{2})\.(\d{2})", reg_raw)
    if not reg_m:
        return None
    reg_year = 2000 + int(reg_m.group(1))
    reg_month = int(reg_m.group(2))
    reg_day = int(reg_m.group(3))
    try:
        reg_date = datetime(reg_year, reg_month, reg_day).date()
    except ValueError:
        return None

    # 최근 60일 이내 공고만
    if (today - reg_date).days > 60:
        return None

    # 지역 추출
    district = ""
    for d in GG_DISTRICTS:
        if d in title:
            district = f"{d}시" if d not in title.replace(f"{d}시", "") else f"{d}시"
            # 간단히 지역명 + "시"
            district = f"{d}시"
            break

    return {
        "id": f"gh_{article_no}",
        "name": title,
        "region": "경기",
        "district": district,
        "address": "",
        "period": "",
        "rcept_end": "",
        "notice_date": reg_date.strftime("%Y-%m-%d"),
        "total_units": "",
        "house_type": "공공임대/분양",
        "constructor": "경기주택도시공사",
        "url": GH_DETAIL_URL_TEMPLATE.format(article_no=article_no),
        "speculative_zone": "",
        "price_controlled": "",
        "house_category": "GH 공공주택",
        "size": "",
        "schedule_source": "unavailable",
    }


def fetch(months_back: int = 2, active_only: bool = True) -> list[dict]:
    """GH 공고 리스트 크롤링 (최대 3페이지). active_only는 상위 레벨에서 적용."""
    today = datetime.now().date()
    results: list[dict] = []

    # 3페이지까지 순회 (주택 구분 공고만 필터이므로 더 넉넉히)
    for page in range(1, 4):
        url = f"{GH_LIST_URL}?pageIndex={page}&article.offset={(page - 1) * 10}&articleLimit=10"
        try:
            r = requests.get(
                url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 k-apt-alert/2.7"},
            )
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"GH list page {page} fetch failed: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table")
        if not table:
            break

        page_count = 0
        for row in table.find_all("tr"):
            try:
                ann = _parse_gh_row(row, today)
                if ann:
                    results.append(ann)
                    page_count += 1
            except Exception as e:
                logger.debug(f"GH row parse skipped: {e}")
                continue

        # 이 페이지에 유효 공고 0건이면 더 이상 진행하지 않음
        if page_count == 0 and page > 1:
            break

    # 중복 제거 (동일 ID)
    seen = set()
    unique = []
    for a in results:
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        unique.append(a)

    logger.info(f"GH: {len(unique)} 주택 공고 추출")
    return unique
