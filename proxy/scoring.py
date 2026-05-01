"""결정론적 가점·특공·자격 판정.

SKILL.md에 자연어로만 적혀 있던 계산 로직을 코드로 이식.
LLM이 매번 계산해서 틀리는 위험(특히 통장 가점, 미성년 인정 한도)을 차단.

청약홈 가점제 공식 (총 84점):
- 무주택 기간: 최대 32점 (1년 미만 2점, 1년부터 2점/년)
- 부양가족: 최대 35점 (0명 5점, 1명당 +5점, 6명 이상 35점)
- 통장 가입기간: 최대 17점 (6개월 미만 1점, 6~12개월 2점, 1년부터 1점/년)

미성년 통장 인정:
- 2024.7.1. 이전 가입분: 최대 2년
- 2024.7.1. 이후 가입분: 최대 5년 (2024.7.1. 시행)
"""

from datetime import date


# ─── 무주택 기간 ────────────────────────────────────────────
def calc_no_house_score(years: float) -> int:
    """무주택 기간 가점 (최대 32점).

    1년 미만 2점, 1년부터 매년 2점, 15년 이상 32점.
    만 30세 이상 또는 혼인신고일 중 늦은 시점부터 기산 (호출자 책임).
    """
    if years < 0:
        return 0
    if years < 1:
        return 2
    return min(2 + int(years) * 2, 32)


# ─── 부양가족 ──────────────────────────────────────────────
def calc_family_score(dependents: int) -> int:
    """부양가족 가점 (최대 35점).

    0명 5점, 1명 10점, 2명 15점, ..., 6명 이상 35점.
    """
    if dependents < 0:
        return 5
    return min(5 + dependents * 5, 35)


# ─── 통장 가입기간 ──────────────────────────────────────────
def calc_account_score(years: float) -> int:
    """청약통장 가입기간 가점 (최대 17점).

    6개월 미만 1점, 6개월~1년 2점, 1년부터 1년당 1점, 15년 이상 17점.
    """
    if years < 0.5:
        return 1
    if years < 1.0:
        return 2
    # 1년 = 3점, 2년 = 4점, ..., 15년+ = 17점
    return min(int(years) + 2, 17)


def adjust_account_minor_cap(
    total_years: float,
    minor_years_pre_2024: float = 0.0,
    minor_years_post_2024: float = 0.0,
) -> float:
    """미성년 가입분 인정 한도 적용.

    - 2024.7.1. 이전 가입분: 최대 2년만 인정 (초과분 차감)
    - 2024.7.1. 이후 가입분: 최대 5년만 인정 (초과분 차감)

    Args:
        total_years: 통장 총 가입기간
        minor_years_pre_2024: 만 19세 이전이면서 2024.7.1. 이전에 가입한 기간
        minor_years_post_2024: 만 19세 이전이면서 2024.7.1. 이후 가입분

    Returns:
        인정 가능한 가입기간
    """
    deduct = 0.0
    if minor_years_pre_2024 > 2.0:
        deduct += minor_years_pre_2024 - 2.0
    if minor_years_post_2024 > 5.0:
        deduct += minor_years_post_2024 - 5.0
    return max(0.0, total_years - deduct)


# ─── 종합 가점 ──────────────────────────────────────────────
def calc_total_score(profile: dict) -> dict:
    """프로필 → 가점 항목별 점수 + 합계.

    profile schema:
      no_house_years: float (무주택 기간)
      dependents: int (부양가족 수)
      subscription_account: {
        years: float,
        minor_years_pre_2024: float (선택, 기본 0),
        minor_years_post_2024: float (선택, 기본 0),
      }
    """
    no_house_yrs = float(profile.get("no_house_years", 0))
    dependents = int(profile.get("dependents", 0))

    acct = profile.get("subscription_account", {})
    raw_years = float(acct.get("years", 0))
    adjusted = adjust_account_minor_cap(
        raw_years,
        float(acct.get("minor_years_pre_2024", 0)),
        float(acct.get("minor_years_post_2024", 0)),
    )

    no_house = calc_no_house_score(no_house_yrs)
    family = calc_family_score(dependents)
    account = calc_account_score(adjusted)

    return {
        "no_house": no_house,
        "family": family,
        "account": account,
        "account_adjusted_years": adjusted,
        "total": no_house + family + account,
        "max_total": 84,
    }


# ─── 특별공급 자격 ──────────────────────────────────────────
def is_eligible_special(profile: dict, special_type: str) -> tuple[bool, str]:
    """특별공급 자격 판정. (자격 여부, 사유) 반환.

    지원 타입: 신혼부부, 생애최초, 다자녀, 노부모부양, 청년
    """
    no_house = bool(profile.get("no_house", True))
    ever_owned = bool(profile.get("ever_owned_house", False))
    acct = profile.get("subscription_account", {})
    years = float(acct.get("years", 0))

    if special_type == "신혼부부":
        if not no_house:
            return False, "현재 주택 보유 — 무주택 요건 미충족"
        marry = profile.get("marriage_date", "")
        if not marry:
            return False, "혼인신고일 미입력"
        try:
            y, m, d = map(int, marry.split("-"))
            elapsed = (date.today() - date(y, m, d)).days / 365.25
            if elapsed > 7.0:
                return False, f"혼인 {elapsed:.1f}년 경과 — 7년 이내 요건 미충족"
            return True, f"혼인 {elapsed:.1f}년차 + 무주택 충족"
        except (ValueError, IndexError):
            return False, "혼인신고일 형식 오류 (YYYY-MM-DD 필요)"

    if special_type == "생애최초":
        if not no_house:
            return False, "현재 주택 보유 — 무주택 요건 미충족"
        if ever_owned:
            return False, "과거 주택 소유 이력 — 생애최초 요건 미충족"
        if years < 2.0:
            return False, f"통장 {years:.1f}년 — 2년 이상 요건 미충족"
        return True, f"통장 {years:.1f}년 + 무주택 + 1주택 무이력 충족"

    if special_type == "다자녀":
        children = profile.get("children", [])
        minor = sum(1 for c in children if c.get("age", 99) < 19)
        if minor < 2:
            return False, f"미성년 자녀 {minor}명 — 2명 이상 요건 미충족"
        return True, f"미성년 자녀 {minor}명 충족"

    if special_type == "노부모부양":
        if profile.get("dependent_parents_3y", False):
            return True, "65세 이상 직계존속 3년 동거 충족 (자가신고)"
        return False, "65세 이상 직계존속 3년 동거 미체크 (프로필 dependent_parents_3y)"

    if special_type == "청년":
        age = int(profile.get("age", 99))
        if age > 39:
            return False, f"만 {age}세 — 만 19~39세 요건 미충족"
        if not no_house:
            return False, "현재 주택 보유 — 무주택 요건 미충족"
        return True, f"만 {age}세 + 무주택 충족"

    return False, f"미지원 특공 타입: {special_type}"


# ─── 1순위 자격 판정 ────────────────────────────────────────
METRO_REGIONS = {"서울", "경기", "인천"}

# 지역별 납입횟수 요건 (2024년 기준)
# 투기과열지구: 24회 / 수도권(청약과열제외): 12회 / 기타: 6회
def _required_deposit_count(speculative_zone: str, region: str) -> tuple[int, str]:
    """(필요납입횟수, 지역구분명) 반환."""
    sz = str(speculative_zone or "").strip().upper()
    if sz in ("Y", "1", "TRUE"):
        return 24, "투기과열지구"
    if region in METRO_REGIONS:
        return 12, "수도권"
    return 6, "기타 지역"


def is_eligible_first_priority(profile: dict, ann: dict) -> dict:
    """1순위 청약 자격 판정.

    Returns:
        {
          "eligible": bool,
          "reason": str,
          "required_count": int — 해당 지역·구역 납입 요건,
          "user_count": int — 프로필 납입 횟수,
          "zone": str — 지역 구분,
          "warnings": list[str] — 자동 확인 불가 항목 경고,
        }
    """
    acct = profile.get("subscription_account", {})
    user_count = int(acct.get("deposit_count", 0))
    speculative_zone = ann.get("speculative_zone", "")
    region = ann.get("region", "")
    required_count, zone_label = _required_deposit_count(speculative_zone, region)

    prev_win = profile.get("previous_win", "없음")
    housing_count = int(profile.get("housing_count", 0))
    no_house = bool(profile.get("no_house", True))

    fails: list[str] = []
    warnings: list[str] = []

    # 납입횟수 체크
    if user_count < required_count:
        fails.append(f"납입 {user_count}회 — {required_count}회 이상 필요")

    # 5년 이내 당첨 이력
    if prev_win == "5년이내":
        fails.append("5년 이내 당첨 이력 — 재당첨 제한 기간 중")

    # 투기과열지구 무주택 요건
    sz = str(speculative_zone or "").strip().upper()
    if sz in ("Y", "1", "TRUE") and not no_house:
        fails.append("주택 보유 — 투기과열지구 1순위는 무주택 필수")

    # 자동 확인 불가 항목 경고
    warnings.append("거주지역 요건(해당 지역 거주기간)은 공고문에서 확인 필요")
    warnings.append("세대구성원 전원 무주택 여부는 공고문 기준으로 자가 확인 필요")

    if fails:
        return {
            "eligible": False,
            "reason": " / ".join(fails),
            "required_count": required_count,
            "user_count": user_count,
            "zone": zone_label,
            "warnings": warnings,
        }
    return {
        "eligible": True,
        "reason": f"{zone_label} 1순위 충족 (납입 {user_count}회 ≥ {required_count}회)",
        "required_count": required_count,
        "user_count": user_count,
        "zone": zone_label,
        "warnings": warnings,
    }


# ─── 경쟁률 통계 추정 ─────────────────────────────────────────
# 2024-2025년 청약홈 결과 기반 경험적 참고치 (단위: 경쟁률, 평균당첨가점)
_COMPETITION_STATS: dict[str, tuple[int, int | None]] = {
    # (지역_투기과열여부_평형) → (평균경쟁률:1, 평균당첨가점)
    "서울_Y_소형": (160, 70), "서울_Y_중형": (90, 63), "서울_Y_대형": (30, None),
    "서울_N_소형": (85, 59), "서울_N_중형": (45, 53), "서울_N_대형": (18, None),
    "경기_Y_소형": (65, 56), "경기_Y_중형": (38, 49), "경기_Y_대형": (12, None),
    "경기_N_소형": (28, 43), "경기_N_중형": (16, 36), "경기_N_대형": (7, None),
    "인천_N_소형": (18, 36), "인천_N_중형": (9, 28), "인천_N_대형": (5, None),
    "기타_N_소형": (9, 26), "기타_N_중형": (5, 19), "기타_N_대형": (3, None),
}

_SIZE_BUCKET = {"소형": "소형", "중형": "중형", "대형": "대형"}


def _size_to_bucket(size_str: str) -> str:
    """size 필드('소형/중형', '중형' 등) → 단일 버킷. 복합이면 첫 번째."""
    if not size_str:
        return "중형"
    first = size_str.split("/")[0].strip()
    return _SIZE_BUCKET.get(first, "중형")


def estimate_competition(ann: dict) -> dict:
    """공고 정보 기반 경쟁률·커트라인 통계 추정.

    Returns:
        {
          "avg_rate": int — 평균 경쟁률 (N:1),
          "avg_cutoff_score": int | None — 평균 당첨 가점 (가점제 해당 시),
          "note": str — 추정 근거 및 주의사항,
          "source": "statistical_estimate",
        }
    """
    region = ann.get("region", "")
    speculative_zone = str(ann.get("speculative_zone", "") or "").strip().upper()
    sz_flag = "Y" if speculative_zone in ("Y", "1", "TRUE") else "N"
    size_bucket = _size_to_bucket(ann.get("size", ""))

    if region in METRO_REGIONS:
        region_key = region if region in ("서울", "경기", "인천") else "경기"
    else:
        region_key = "기타"

    key = f"{region_key}_{sz_flag}_{size_bucket}"
    stats = _COMPETITION_STATS.get(key, _COMPETITION_STATS.get(f"{region_key}_N_중형", (5, 20)))
    avg_rate, avg_cutoff = stats

    # 대형(85m²+)은 추첨제 위주 → 가점 무관
    if size_bucket == "대형":
        cutoff_note = "85m² 초과는 추첨제 비율 높아 가점 무관"
    elif avg_cutoff:
        cutoff_note = f"평균 당첨 가점 약 {avg_cutoff}점 (참고치)"
    else:
        cutoff_note = ""

    zone_label = "투기과열지구" if sz_flag == "Y" else "일반지역"
    return {
        "avg_rate": avg_rate,
        "avg_cutoff_score": avg_cutoff,
        "note": (
            f"[통계 추정치] {region} {size_bucket} ({zone_label}) "
            f"기준 평균 {avg_rate}:1 수준. {cutoff_note}"
        ),
        "source": "statistical_estimate",
        "disclaimer": "2024-2025년 청약홈 결과 기반 경험적 참고치. 실제 경쟁률은 공고별·시점별 크게 다름.",
    }


# ─── 카테고리 매칭 ──────────────────────────────────────────
NO_ACCOUNT_REQUIRED = {"APT잔여세대", "임의공급", "오피스텔/도시형"}


def match_announcement(profile: dict, ann: dict) -> dict:
    """공고 ↔ 프로필 매칭 결과.

    Returns:
        {
          "category_match": bool — 선호 카테고리 일치 여부
          "region_match": bool — 선호 지역 일치 여부
          "min_units_ok": bool — 최소 세대수 요건 충족
          "needs_account": bool — 청약통장 필요 여부
          "fit_level": "high"|"medium"|"low" — 종합 적합도
        }
    """
    cat = ann.get("house_category", "")
    region = ann.get("region", "")
    units = int(str(ann.get("total_units", "0")).replace(",", "") or "0")

    pref_cats = set(profile.get("preferred_categories", []))
    pref_regions = set(profile.get("preferred_regions", []))
    min_units = int(profile.get("min_units", 0))

    cat_match = not pref_cats or cat in pref_cats
    region_match = not pref_regions or region in pref_regions or region == "전국"
    units_ok = units == 0 or units >= min_units
    needs_account = cat not in NO_ACCOUNT_REQUIRED

    score = sum([cat_match, region_match, units_ok])
    if score == 3:
        fit = "high"
    elif score == 2:
        fit = "medium"
    else:
        fit = "low"

    return {
        "category_match": cat_match,
        "region_match": region_match,
        "min_units_ok": units_ok,
        "needs_account": needs_account,
        "fit_level": fit,
    }
