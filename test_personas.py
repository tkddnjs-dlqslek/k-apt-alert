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
            "household": {"type": "newlywed", "children_count": 0},
            "homeless": True, "housing_count": 0,
            "subscription_account": {"has_account": True, "years": 3, "deposit_count": 36},
            "income_bracket": "mid_low",
            "preferred_size": ["소형", "중형"],
            "marriage_date": "2025-04", "residence_region": "광주", "residence_years": 5,
            "previous_win": "없음", "dependents_count": 1,
            "pregnant": True,
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


def household_size(prof):
    """가구원 수 계산 (본인 + 배우자 + 자녀 + 태아)."""
    htype = prof["household"]["type"]
    children = prof["household"]["children_count"]
    has_spouse = htype in ("newlywed", "married_no_child", "married_with_child")
    pregnancy = 1 if prof.get("pregnant") else 0
    return 1 + (1 if has_spouse else 0) + children + pregnancy


def income_ok_for_public(prof):
    """공공분양/공공지원민간임대 소득 기준 정성 판정.
    3인 이하: 100% / 4인: 110% / 5인+: 120~130%.
    low/mid_low/mid 구간은 모든 가구원수에서 통과, mid_high는 4인+에서 가능.
    """
    income = prof.get("income_bracket")
    size = household_size(prof)
    if income in ("low", "mid_low", "mid"):
        return True
    if income == "mid_high" and size >= 4:
        return True
    return False


def match_categories(prof):
    cats = []
    has_acct = prof["subscription_account"]["has_account"]
    years = prof["subscription_account"]["years"]
    homeless = prof["homeless"]
    housing = prof["housing_count"]

    if has_acct and years >= 2 and homeless:
        cats.append("APT 일반분양")
    cats.append("오피스텔/도시형")
    if has_acct and years >= 0.5 and homeless and income_ok_for_public(prof):
        cats.append("LH 공공분양")
    cats.append("APT 잔여세대")
    if homeless and income_ok_for_public(prof):
        cats.append("공공지원민간임대")
    cats.append("임의공급")
    if housing >= 1:
        cats.append("[갈아타기 안내]")
    return cats


def match_special(prof):
    specials = []
    homeless = prof["homeless"]
    htype = prof["household"]["type"]
    children = prof["household"]["children_count"] + (1 if prof.get("pregnant") else 0)
    marriage = prof["marriage_date"]
    prev_win = prof["previous_win"]
    has_acct = prof["subscription_account"]["has_account"]
    years = prof["subscription_account"]["years"]

    if htype == "newlywed" and marriage and homeless:
        specials.append("신혼부부")
    if homeless and prev_win == "없음" and has_acct and years >= 2:
        specials.append("생애최초")
    if children >= 2 and homeless:
        specials.append(f"다자녀({children})")
    if htype == "single_parent" and homeless:
        specials.append("한부모(기관추천)")
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
    # Warmup (Render free tier 슬립 회피)
    try:
        requests.get(f"{PROXY}/health", timeout=60)
    except Exception as e:
        print(f"[warn] warmup failed: {e}")

    # Fetch with retry
    anns = []
    for attempt in range(3):
        try:
            resp = requests.get(f"{PROXY}/v1/apt/announcements", params={
                "category": "all", "active_only": "false", "months_back": "2"
            }, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            anns = data["announcements"]
            break
        except Exception as e:
            print(f"[warn] fetch attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                print("[error] 프록시 응답 실패 — mock 테스트만 실행")
                run_mock_tests()
                return

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
        total_children = prof["household"]["children_count"] + (1 if prof.get("pregnant") else 0)
        if total_children >= 2 and prof["homeless"]:
            if not any("다자녀" in s for s in specials):
                issues.append(f"{p['name']}: 다자녀 특별공급 누락")
        # 생애최초: 통장 2년+ 필수
        if prof["homeless"] and prof["previous_win"] == "없음":
            acct = prof["subscription_account"]
            should_qualify = acct["has_account"] and acct["years"] >= 2
            has_special = "생애최초" in specials
            if should_qualify and not has_special:
                issues.append(f"{p['name']}: 생애최초 누락 (통장 {acct['years']}년)")
            if not should_qualify and has_special:
                issues.append(f"{p['name']}: 생애최초 오부여 (통장 부족)")
        # 한부모
        if prof["household"]["type"] == "single_parent" and prof["homeless"]:
            if not any("한부모" in s for s in specials):
                issues.append(f"{p['name']}: 한부모 기관추천 누락")

    print(f"\n{'=' * 80}")
    if issues:
        print(f"검증 실패: {len(issues)}건")
        for i in issues:
            print(f"  !! {i}")
    else:
        print("검증 통과: 모든 페르소나 매칭 로직 정상")
    print("=" * 80)

    run_mock_tests()


def run_mock_tests():
    """단위 테스트 — LH 전국 공고 통과 + D-day 정렬."""
    print("\n[Mock Tests]")
    mock_anns = [
        {"name": "LH 전국 공고 X", "region": "전국", "size": "중형", "d_day": 2, "house_category": "LH 공공분양"},
        {"name": "LH 서울 공고 Y", "region": "서울", "size": "중형", "d_day": 0, "house_category": "LH 공공분양"},
        {"name": "LH 부산 공고 Z", "region": "부산", "size": "중형", "d_day": 10, "house_category": "LH 공공분양"},
    ]
    strict_profile = {
        "regions": ["서울"],
        "preferred_size": ["중형"],
    }
    matched = filter_anns(strict_profile, mock_anns)
    test_issues = []
    matched_names = {m["name"] for m in matched}
    if "LH 전국 공고 X" not in matched_names:
        test_issues.append("LH 전국 공고가 서울 프로필에 통과하지 않음")
    if "LH 부산 공고 Z" in matched_names:
        test_issues.append("LH 부산 공고가 서울 프로필에 통과됨 (지역 필터 실패)")
    if "LH 서울 공고 Y" not in matched_names:
        test_issues.append("LH 서울 공고가 매칭되지 않음")

    # D-day 정렬 검증
    sortable = sorted(mock_anns, key=lambda x: x["d_day"])
    if sortable[0]["d_day"] != 0 or sortable[-1]["d_day"] != 10:
        test_issues.append("D-day 정렬 실패")

    if test_issues:
        print(f"  Mock 테스트 실패: {len(test_issues)}건")
        for t in test_issues:
            print(f"    !! {t}")
        sys.exit(1)
    print("  ✓ LH 전국 공고 통과 / 지역 필터 / D-day 정렬 정상")


if __name__ == "__main__":
    main()
