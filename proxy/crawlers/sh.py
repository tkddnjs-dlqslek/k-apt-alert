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
# SH 공급 빈도 높은 단지/지구 위주로 확장 (자치구별 고유 키워드만)
DISTRICT_KEYWORDS = {
    # 강서구
    "마곡": "강서구", "가양": "강서구", "등촌": "강서구", "방화": "강서구",
    "발산": "강서구", "내발산": "강서구",
    # 강동구
    "고덕": "강동구", "강일": "강동구", "둔촌": "강동구", "암사": "강동구",
    "천호": "강동구", "성내": "강동구",
    # 송파구
    "위례": "송파구", "거여": "송파구", "마천": "송파구", "잠실": "송파구",
    "문정": "송파구", "장지": "송파구", "오금": "송파구",
    # 강남구
    "세곡": "강남구", "자곡": "강남구", "수서": "강남구", "일원": "강남구",
    "개포": "강남구", "압구정": "강남구", "도곡": "강남구",
    # 서초구
    "반포": "서초구", "내곡": "서초구", "우면": "서초구", "양재": "서초구",
    "방배": "서초구",
    # 성동구
    "성수": "성동구", "옥수": "성동구", "금호": "성동구", "응봉": "성동구",
    "행당": "성동구",
    # 광진구
    "구의": "광진구", "자양": "광진구", "화양": "광진구", "능동": "광진구",
    # 구로구
    "항동": "구로구", "오류": "구로구", "천왕": "구로구", "고척": "구로구",
    "개봉": "구로구", "신도림": "구로구",
    # 중랑구
    "신내": "중랑구", "양원": "중랑구", "면목": "중랑구", "묵동": "중랑구",
    "망우": "중랑구", "상봉": "중랑구",
    # 성북구
    "장위": "성북구", "길음": "성북구", "정릉": "성북구", "미아": "성북구",
    "돈암": "성북구", "삼선": "성북구",
    # 강북구
    "수유": "강북구", "번동": "강북구", "우이": "강북구",
    # 노원구
    "상계": "노원구", "중계": "노원구", "월계": "노원구", "공릉": "노원구",
    "하계": "노원구",
    # 도봉구
    "방학": "도봉구", "쌍문": "도봉구", "창동": "도봉구",
    # 양천구
    "신정": "양천구", "신월": "양천구", "목동": "양천구",
    # 영등포구
    "신길": "영등포구", "당산": "영등포구", "양평동": "영등포구",
    "여의도": "영등포구", "문래": "영등포구", "대림": "영등포구",
    # 금천구
    "가산": "금천구", "독산": "금천구", "시흥동": "금천구",
    # 동대문구
    "답십리": "동대문구", "장안": "동대문구", "휘경": "동대문구",
    "청량리": "동대문구", "용두": "동대문구", "전농": "동대문구",
    # 은평구
    "응암": "은평구", "불광": "은평구", "진관": "은평구", "녹번": "은평구",
    "갈현": "은평구", "수색": "은평구",
    # 서대문구
    "홍은": "서대문구", "홍제": "서대문구", "남가좌": "서대문구",
    "북가좌": "서대문구", "북아현": "서대문구",
    # 마포구
    "상암": "마포구", "성산": "마포구", "망원": "마포구", "합정": "마포구",
    "공덕": "마포구", "도화": "마포구", "아현": "마포구",
    # 동작구
    "상도": "동작구", "흑석": "동작구", "노량진": "동작구", "사당": "동작구",
    "대방": "동작구", "신대방": "동작구",
    # 관악구
    "신림": "관악구", "봉천": "관악구", "남현": "관악구",
    # 용산구
    "한남": "용산구", "이태원": "용산구", "보광": "용산구", "원효": "용산구",
    "후암": "용산구", "이촌": "용산구",
    # 종로구
    "평창": "종로구", "부암": "종로구", "삼청": "종로구",
    # 중구
    "을지로": "중구", "신당": "중구", "황학": "중구",
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
