"""8명 페르소나 E2E 시뮬레이션 테스트."""
import json
import os
import sys
import requests

PROXY = os.environ.get("PROXY_URL", "http://localhost:8002")

personas = [
    {
        "name": "P1. 김도현 (27, 인천 사회초년생, 연봉 3200만)",
        "profile": {
            "birth_year": 1999, "age": 27,
            "regions": ["서울", "경기", "인천"],
            "household": {"type": "single", "children_count": 0},
            "homeless": True, "housing_count": 0,
            "subscription_account": {"has_account": True, "years": 2, "deposit_count": 24},
            "income_bracket": "mid_low",
            "preferred_size": ["소형"],
            "marriage_date": None, "residence_region": "인천", "residence_years": 3,
            "previous_win": "없음", "dependents_count": 0,
        },
    },
    {
        "name": "P2. 박서윤 부부 (31/33, 부산 신혼, 맞벌이 7500만)",
        "profile": {
            "birth_year": 1995, "age": 31,
            "regions": ["부산"],
            "household": {"type": "newlywed", "children_count": 0},
            "homeless": True, "housing_count": 0,
            "subscription_account": {"has_account": True, "years": 6, "deposit_count": 72},
            "income_bracket": "mid_high",
            "preferred_size": ["중형"],
            "marriage_date": "2024-05", "residence_region": "부산", "residence_years": 5,
            "previous_win": "없음", "dependents_count": 1,
        },
    },
    {
        "name": "P3. 최영수 (48, 경기 분당, 2주택 갈아타기)",
        "profile": {
            "birth_year": 1978, "age": 48,
            "regions": ["서울", "경기"],
            "household": {"type": "married_with_child", "children_count": 2},
            "homeless": False, "housing_count": 2,
            "subscription_account": {"has_account": True, "years": 18, "deposit_count": 216},
            "income_bracket": "mid_high",
            "preferred_size": ["대형"],
            "marriage_date": "2005-03", "residence_region": "경기", "residence_years": 10,
            "previous_win": "없음", "dependents_count": 3,
        },
    },
    {
        "name": "P4. 윤미라 (34, 대전 한부모, 자녀1, 연봉 2800만)",
        "profile": {
            "birth_year": 1992, "age": 34,
            "regions": ["대전", "세종"],
            "household": {"type": "single_parent", "children_count": 1},
            "homeless": True, "housing_count": 0,
            "subscription_account": {"has_account": True, "years": 4, "deposit_count": 48},
            "income_bracket": "low",
            "preferred_size": ["소형", "중형"],
            "marriage_date": None, "residence_region": "대전", "residence_years": 10,
            "previous_win": "없음", "dependents_count": 1,
        },
    },
    {
        "name": "P5. 한지우 (25, 제주 대학원생, 통장없음, 소득없음)",
        "profile": {
            "birth_year": 2001, "age": 25,
            "regions": ["제주"],
            "household": {"type": "single", "children_count": 0},
            "homeless": True, "housing_count": 0,
            "subscription_account": {"has_account": False, "years": 0, "deposit_count": 0},
            "income_bracket": None,
            "preferred_size": [],
            "marriage_date": None, "residence_region": "제주", "residence_years": 3,
            "previous_win": "없음", "dependents_count": 0,
        },
    },
    {
        "name": "P6. 김태호 (38, 세종 공무원, 자녀3, 통장 10년)",
        "profile": {
            "birth_year": 1988, "age": 38,
            "regions": ["세종", "대전"],
            "household": {"type": "married_with_child", "children_count": 3},
            "homeless": True, "housing_count": 0,
            "subscription_account": {"has_account": True, "years": 10, "deposit_count": 120},
            "income_bracket": "mid",
            "preferred_size": ["중형", "대형"],
            "marriage_date": "2015-06", "residence_region": "세종", "residence_years": 6,
            "previous_win": "없음", "dependents_count": 4,
        },
    },
    {
        "name": "P7. 오수빈 부부 (29/30, 광주 신혼+임신, 합산 5000만)",
        "profile": {
            "birth_year": 1997, "age": 29,
            "regions": ["광주"],
            "household": {"type": "newlywed", "children_count": 1},
            "homeless": True, "housing_count": 0,
            "subscription_account": {"has_account": True, "years": 3, "deposit_count": 36},
            "income_bracket": "mid_low",
            "preferred_size": ["소형", "중형"],
            "marriage_date": "2025-04", "residence_region": "광주", "residence_years": 5,
            "previous_win": "없음", "dependents_count": 2,
        },
    },
    {
        "name": "P8. 이봉재 (62, 서울→강원 귀촌, 1주택, 연금 3600만)",
        "profile": {
            "birth_year": 1964, "age": 62,
            "regions": ["강원"],
            "household": {"type": "married_no_child", "children_count": 0},
            "homeless": False, "housing_count": 1,
            "subscription_account": {"has_account": True, "years": 25, "deposit_count": 300},
            "income_bracket": "mid_low",
            "preferred_size": ["중형"],
            "marriage_date": "1990-01", "residence_region": "서울", "residence_years": 30,
            "previous_win": "없음", "dependents_count": 1,
        },
    },
]


def match_categories(prof):
    cats = []
    has_acct = prof["subscription_account"]["has_account"]
    years = prof["subscription_account"]["years"]
    homeless = prof["homeless"]
    housing = prof["housing_count"]
    income = prof["income_bracket"]

    if has_acct and years >= 2 and homeless:
        cats.append("APT 일반분양")
    if True:
        cats.append("오피스텔/도시형")
    if has_acct and years >= 0.5 and homeless and income in ("low", "mid_low", "mid"):
        cats.append("LH 공공분양")
    cats.append("APT 잔여세대")
    if homeless and income in ("low", "mid_low", "mid"):
        cats.append("공공지원민간임대")
    cats.append("임의공급")
    if housing >= 1:
        cats.append("[갈아타기 안내]")
    return cats


def match_special(prof):
    specials = []
    homeless = prof["homeless"]
    htype = prof["household"]["type"]
    children = prof["household"]["children_count"]
    marriage = prof["marriage_date"]
    prev_win = prof["previous_win"]

    if htype == "newlywed" and marriage and homeless:
        specials.append("신혼부부")
    if homeless and prev_win == "없음":
        specials.append("생애최초")
    if children >= 2 and homeless:
        specials.append(f"다자녀({children})")
    return specials


def calc_score(prof):
    age = prof["age"]
    deps = prof["dependents_count"]
    years = prof["subscription_account"]["years"]
    homeless = prof["homeless"]

    if not homeless:
        h = 0
    elif age >= 30:
        h = min(2 + (age - 30) * 2, 32)
    else:
        h = 0

    d = min(5 + deps * 5, 35)
    a = min(years * 2, 17)
    return h, d, a


def filter_anns(prof, anns):
    regions = set(prof["regions"])
    sizes = set(prof.get("preferred_size", []))
    matched = []
    for ann in anns:
        r = ann.get("region", "")
        if r not in regions and r != "전국":
            continue
        if sizes and ann.get("size"):
            ann_sizes = set(ann["size"].split("/"))
            if not ann_sizes & sizes:
                continue
        matched.append(ann)
    return matched


def main():
    # Fetch all announcements
    resp = requests.get(f"{PROXY}/v1/apt/announcements", params={
        "category": "all", "active_only": "false", "months_back": "2"
    })
    data = resp.json()
    anns = data["announcements"]

    print("=" * 80)
    print(f"페르소나 E2E 시뮬레이션 (전체 공고 {len(anns)}건)")
    print("=" * 80)

    issues = []

    for p in personas:
        prof = p["profile"]
        print(f"\n{'─' * 60}")
        print(f"  {p['name']}")
        print(f"{'─' * 60}")

        cats = match_categories(prof)
        print(f"  추천 유형: {' / '.join(cats)}")

        specials = match_special(prof)
        print(f"  특별공급: {' / '.join(specials) if specials else '해당 없음'}")

        h, d, a = calc_score(prof)
        total = h + d + a
        print(f"  추정 가점: {total}점/84점 (무주택 {h} + 부양가족 {d} + 통장 {a})")

        matched = filter_anns(prof, anns)
        print(f"  매칭 공고: {len(matched)}건")
        for m in matched[:3]:
            print(f"    - {m['name'][:25]} | {m['region']} {m.get('district','')} | {m['house_category']}")

        # Validate
        if prof["homeless"] and prof["subscription_account"]["has_account"] and prof["subscription_account"]["years"] >= 2:
            if "APT 일반분양" not in cats:
                issues.append(f"{p['name']}: APT 일반분양 누락")
        if prof["housing_count"] >= 1 and "[갈아타기 안내]" not in cats:
            issues.append(f"{p['name']}: 갈아타기 안내 누락")
        if prof["household"]["type"] == "newlywed" and prof["homeless"] and "신혼부부" not in specials:
            issues.append(f"{p['name']}: 신혼부부 특별공급 누락")
        if prof["household"]["children_count"] >= 2 and prof["homeless"]:
            if not any("다자녀" in s for s in specials):
                issues.append(f"{p['name']}: 다자녀 특별공급 누락")

    print(f"\n{'=' * 80}")
    if issues:
        print(f"검증 실패: {len(issues)}건")
        for i in issues:
            print(f"  !! {i}")
    else:
        print("검증 통과: 모든 페르소나 매칭 로직 정상")
    print("=" * 80)


if __name__ == "__main__":
    main()
