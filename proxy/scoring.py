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
