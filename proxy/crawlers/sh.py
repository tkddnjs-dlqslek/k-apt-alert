"""서울주택도시공사(SH) 공고 크롤러.

공식 OpenAPI 없음. 주택임대(multi_itm_seq=2) + 주택분양(multi_itm_seq=1) 게시판 HTML 스크래핑.

페이지 구조:
- table[0] row: 번호 / 제목 / 담당부서 / 등록일(YYYY-MM-DD) / 조회수
- 제목 <a onclick="getDetailView('303101')">
- 상세 URL: .../m_247/view.do?seq={seq}&multi_itm_seq={1 or 2} (GET 가능)
"""

import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SH_LIST_LEASE = "https://www.i-sh.co.kr/app/lay2/program/S48T1581C563/www/brd/m_247/list.do?multi_itm_seq=2"
SH_LIST_SALE = "https://www.i-sh.co.kr/app/lay2/program/S48T1581C563/www/brd/m_247/list.do?multi_itm_seq=1"
SH_DETAIL_URL_TEMPLATE = "https://www.i-sh.co.kr/app/lay2/program/S48T1581C563/www/brd/m_247/view.do?seq={seq}&multi_itm_seq={board}"

INCLUDE_KEYWORDS = ["모집공고", "분양공고", "입주자 모집", "공급공고", "청약공고", "본청약"]
EXCLUDE_KEYWORDS = ["당첨자", "발표", "계약", "선정", "취소", "변경", "안내문", "결과", "명단"]

# 서울 25개 자치구
SEOUL_DISTRICTS = [
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구",
    "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구",
    "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
]

# 제목 중에 나오는 '지구'·'단지' 같은 키워드로 지역 추정
DISTRICT_KEYWORDS = {
    "마곡": "강서구", "고덕": "강동구", "위례": "송파구", "강일": "강동구",
    "성수": "성동구", "구의": "광진구", "가양": "강서구", "반포": "서초구",
}


def _parse_sh_row(row, board_id: int) -> dict | None:
    cells = row.find_all("td")
    if len(cells) < 5:
        return None

    title_cell = cells[1]
    title = title_cell.get_text(" ", strip=True)
    link = title_cell.find("a")
    if not link:
        return None

    if not any(kw in title for kw in INCLUDE_KEYWORDS):
        return None
    if any(kw in title for kw in EXCLUDE_KEYWORDS):
        return None

    # onclick 에서 seq 추출
    onclick = link.get("onclick", "")
    m = re.search(r"getDetailView\(['\"](\d+)['\"]", onclick)
    if not m:
        return None
    seq = m.group(1)

    # 등록일 (YYYY-MM-DD)
    reg_raw = cells[3].get_text(strip=True)
    try:
        reg_date = datetime.strptime(reg_raw, "%Y-%m-%d").date()
    except ValueError:
        return None

    today = datetime.now().date()
    if (today - reg_date).days > 60:
        return None

    # 지역 추출
    district = ""
    for d in SEOUL_DISTRICTS:
        if d in title:
            district = d
            break
    if not district:
        for kw, d in DISTRICT_KEYWORDS.items():
            if kw in title:
                district = d
                break

    house_type = "공공분양" if board_id == 1 else "공공임대"

    return {
        "id": f"sh_{seq}",
        "name": title,
        "region": "서울",
        "district": district,
        "address": "",
        "period": "",
        "rcept_end": "",
        "notice_date": reg_date.strftime("%Y-%m-%d"),
        "total_units": "",
        "house_type": house_type,
        "constructor": "서울주택도시공사",
        "url": SH_DETAIL_URL_TEMPLATE.format(seq=seq, board=board_id),
        "speculative_zone": "",
        "price_controlled": "",
        "house_category": "SH 공공주택",
        "size": "",
        "schedule_source": "unavailable",
    }


def _fetch_board(list_url: str, board_id: int) -> list[dict]:
    results: list[dict] = []
    try:
        r = requests.get(list_url, timeout=15, headers={"User-Agent": "Mozilla/5.0 k-apt-alert/2.7"})
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"SH board {board_id} fetch failed: {e}")
        return results

    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table")
    if not table:
        return results

    for row in table.find_all("tr"):
        try:
            ann = _parse_sh_row(row, board_id)
            if ann:
                results.append(ann)
        except Exception as e:
            logger.debug(f"SH row parse skipped: {e}")
            continue

    return results


def fetch(months_back: int = 2, active_only: bool = True) -> list[dict]:
    """SH 주택임대 + 주택분양 게시판 통합 크롤링."""
    results: list[dict] = []
    results.extend(_fetch_board(SH_LIST_SALE, 1))   # 분양
    results.extend(_fetch_board(SH_LIST_LEASE, 2))  # 임대
    logger.info(f"SH: {len(results)} 공고 추출 (분양+임대)")
    return results
