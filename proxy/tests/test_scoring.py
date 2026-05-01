"""scoring.py 결정론적 가점·특공·매칭 테스트."""

import pytest

import scoring


# ─── calc_no_house_score ──────────────────────────────────────────────

def test_no_house_under_1yr():
    assert scoring.calc_no_house_score(0) == 2
    assert scoring.calc_no_house_score(0.9) == 2

def test_no_house_1yr():
    assert scoring.calc_no_house_score(1) == 4  # 2 + 1*2

def test_no_house_5yr():
    assert scoring.calc_no_house_score(5) == 12  # 2 + 5*2

def test_no_house_15yr_capped():
    assert scoring.calc_no_house_score(15) == 32
    assert scoring.calc_no_house_score(30) == 32

def test_no_house_negative():
    assert scoring.calc_no_house_score(-1) == 0


# ─── calc_family_score ────────────────────────────────────────────────

def test_family_0():
    assert scoring.calc_family_score(0) == 5

def test_family_1():
    assert scoring.calc_family_score(1) == 10

def test_family_6_capped():
    assert scoring.calc_family_score(6) == 35
    assert scoring.calc_family_score(10) == 35

def test_family_negative_floors_to_5():
    assert scoring.calc_family_score(-1) == 5


# ─── calc_account_score ───────────────────────────────────────────────

def test_account_under_6mo():
    assert scoring.calc_account_score(0.3) == 1

def test_account_6mo_to_1yr():
    assert scoring.calc_account_score(0.5) == 2
    assert scoring.calc_account_score(0.9) == 2

def test_account_1yr():
    assert scoring.calc_account_score(1) == 3   # 1+2

def test_account_3yr():
    assert scoring.calc_account_score(3) == 5   # 3+2 (not years*2!)

def test_account_7yr():
    assert scoring.calc_account_score(7) == 9   # 7+2

def test_account_15yr_capped():
    assert scoring.calc_account_score(15) == 17
    assert scoring.calc_account_score(20) == 17


# ─── adjust_account_minor_cap ─────────────────────────────────────────

def test_minor_cap_no_minor():
    assert scoring.adjust_account_minor_cap(10, 0, 0) == 10.0

def test_minor_cap_pre2024_within_limit():
    # 2년 이내면 차감 없음
    assert scoring.adjust_account_minor_cap(10, 2.0, 0) == 10.0

def test_minor_cap_pre2024_over_limit():
    # 2024.7.1. 이전 미성년 3년 → 초과 1년 차감
    assert scoring.adjust_account_minor_cap(10, 3.0, 0) == 9.0

def test_minor_cap_post2024_within_limit():
    # 5년 이내면 차감 없음
    assert scoring.adjust_account_minor_cap(10, 0, 5.0) == 10.0

def test_minor_cap_post2024_over_limit():
    # 2024.7.1. 이후 미성년 6년 → 초과 1년 차감
    assert scoring.adjust_account_minor_cap(10, 0, 6.0) == 9.0

def test_minor_cap_both_over():
    # pre 3년(1년 초과) + post 7년(2년 초과) → 3년 차감
    assert scoring.adjust_account_minor_cap(15, 3.0, 7.0) == 12.0

def test_minor_cap_floor_at_zero():
    assert scoring.adjust_account_minor_cap(1, 5.0, 0) == 0.0


# ─── calc_total_score ─────────────────────────────────────────────────

def test_total_score_basic():
    profile = {
        "no_house_years": 7,
        "dependents": 1,
        "subscription_account": {"years": 7},
    }
    result = scoring.calc_total_score(profile)
    assert result["no_house"] == 16   # 2 + 7*2
    assert result["family"] == 10     # 5 + 1*5
    assert result["account"] == 9    # 7+2
    assert result["total"] == 35
    assert result["max_total"] == 84

def test_total_score_defaults_to_zero():
    result = scoring.calc_total_score({})
    assert result["no_house"] == 2   # 0년 미만 2점
    assert result["family"] == 5
    assert result["account"] == 1
    assert result["total"] == 8


# ─── is_eligible_special ──────────────────────────────────────────────

def test_special_newlywed_within_7yr():
    profile = {
        "no_house": True,
        "marriage_date": "2022-01-01",
    }
    ok, _ = scoring.is_eligible_special(profile, "신혼부부")
    assert ok is True

def test_special_newlywed_over_7yr():
    profile = {
        "no_house": True,
        "marriage_date": "2015-01-01",
    }
    ok, reason = scoring.is_eligible_special(profile, "신혼부부")
    assert ok is False
    assert "7년" in reason

def test_special_newlywed_no_house_required():
    profile = {"no_house": False, "marriage_date": "2023-01-01"}
    ok, reason = scoring.is_eligible_special(profile, "신혼부부")
    assert ok is False
    assert "무주택" in reason

def test_special_first_time_ok():
    profile = {
        "no_house": True,
        "ever_owned_house": False,
        "subscription_account": {"years": 3},
    }
    ok, _ = scoring.is_eligible_special(profile, "생애최초")
    assert ok is True

def test_special_first_time_under_2yr():
    profile = {
        "no_house": True,
        "ever_owned_house": False,
        "subscription_account": {"years": 1},
    }
    ok, reason = scoring.is_eligible_special(profile, "생애최초")
    assert ok is False
    assert "2년" in reason

def test_special_first_time_ever_owned():
    profile = {
        "no_house": True,
        "ever_owned_house": True,
        "subscription_account": {"years": 3},
    }
    ok, reason = scoring.is_eligible_special(profile, "생애최초")
    assert ok is False
    assert "이력" in reason

def test_special_multi_child_ok():
    profile = {"children": [{"age": 5}, {"age": 10}]}
    ok, _ = scoring.is_eligible_special(profile, "다자녀")
    assert ok is True

def test_special_multi_child_only_one_minor():
    profile = {"children": [{"age": 5}, {"age": 25}]}
    ok, reason = scoring.is_eligible_special(profile, "다자녀")
    assert ok is False
    assert "2명" in reason

def test_special_youth_ok():
    ok, _ = scoring.is_eligible_special({"no_house": True, "age": 29}, "청년")
    assert ok is True

def test_special_youth_over_39():
    ok, reason = scoring.is_eligible_special({"no_house": True, "age": 40}, "청년")
    assert ok is False
    assert "39세" in reason

def test_special_unsupported_type():
    ok, reason = scoring.is_eligible_special({}, "없는타입")
    assert ok is False
    assert "미지원" in reason


# ─── match_announcement ───────────────────────────────────────────────

def test_match_high_all_three():
    profile = {
        "preferred_categories": ["APT"],
        "preferred_regions": ["서울"],
        "min_units": 100,
    }
    ann = {"house_category": "APT", "region": "서울", "total_units": "500"}
    result = scoring.match_announcement(profile, ann)
    assert result["fit_level"] == "high"
    assert result["needs_account"] is True

def test_match_low_region_miss():
    profile = {
        "preferred_categories": ["APT"],
        "preferred_regions": ["서울"],
        "min_units": 0,
    }
    ann = {"house_category": "APT", "region": "부산", "total_units": "300"}
    result = scoring.match_announcement(profile, ann)
    assert result["region_match"] is False
    assert result["fit_level"] in ("medium", "low")

def test_match_no_account_needed_for_officetell():
    profile = {"preferred_categories": [], "preferred_regions": [], "min_units": 0}
    ann = {"house_category": "오피스텔/도시형", "region": "서울", "total_units": "50"}
    result = scoring.match_announcement(profile, ann)
    assert result["needs_account"] is False

def test_match_empty_profile_matches_all():
    profile = {}
    ann = {"house_category": "APT", "region": "경기", "total_units": "200"}
    result = scoring.match_announcement(profile, ann)
    assert result["category_match"] is True
    assert result["region_match"] is True
    assert result["min_units_ok"] is True
    assert result["fit_level"] == "high"


# ─── is_eligible_first_priority ───────────────────────────────────────

def _ann_fp(**kw):
    return {"speculative_zone": "N", "region": "경기", **kw}

def _profile_fp(**kw):
    base = {
        "subscription_account": {"deposit_count": 12},
        "no_house": True,
        "previous_win": "없음",
    }
    base.update(kw)
    return base


def test_1st_priority_metro_ok():
    result = scoring.is_eligible_first_priority(_profile_fp(), _ann_fp(region="서울"))
    assert result["eligible"] is True
    assert result["required_count"] == 12
    assert result["zone"] == "수도권"

def test_1st_priority_metro_fail_count():
    p = _profile_fp(subscription_account={"deposit_count": 6})
    result = scoring.is_eligible_first_priority(p, _ann_fp(region="서울"))
    assert result["eligible"] is False
    assert "12회" in result["reason"]

def test_1st_priority_speculative_24():
    p = _profile_fp(subscription_account={"deposit_count": 24})
    result = scoring.is_eligible_first_priority(p, _ann_fp(speculative_zone="Y"))
    assert result["eligible"] is True
    assert result["required_count"] == 24
    assert "투기과열지구" in result["zone"]

def test_1st_priority_speculative_fail_12():
    p = _profile_fp(subscription_account={"deposit_count": 12})
    result = scoring.is_eligible_first_priority(p, _ann_fp(speculative_zone="Y"))
    assert result["eligible"] is False
    assert "24회" in result["reason"]

def test_1st_priority_others_6():
    p = _profile_fp(subscription_account={"deposit_count": 6})
    result = scoring.is_eligible_first_priority(p, _ann_fp(region="부산"))
    assert result["eligible"] is True
    assert result["required_count"] == 6

def test_1st_priority_prev_win_blocks():
    p = _profile_fp(previous_win="5년이내")
    result = scoring.is_eligible_first_priority(p, _ann_fp())
    assert result["eligible"] is False
    assert "당첨 이력" in result["reason"]

def test_1st_priority_speculative_with_house_blocks():
    p = _profile_fp(no_house=False, subscription_account={"deposit_count": 24})
    result = scoring.is_eligible_first_priority(p, _ann_fp(speculative_zone="Y"))
    assert result["eligible"] is False
    assert "주택 보유" in result["reason"]

def test_1st_priority_always_has_warnings():
    result = scoring.is_eligible_first_priority(_profile_fp(), _ann_fp())
    assert len(result["warnings"]) >= 1


# ─── estimate_competition ─────────────────────────────────────────────

def test_competition_seoul_speculative_small():
    ann = {"region": "서울", "speculative_zone": "Y", "size": "소형"}
    result = scoring.estimate_competition(ann)
    assert result["avg_rate"] == 160
    assert result["avg_cutoff_score"] == 70
    assert result["source"] == "statistical_estimate"

def test_competition_gyeonggi_general_medium():
    ann = {"region": "경기", "speculative_zone": "N", "size": "중형"}
    result = scoring.estimate_competition(ann)
    assert result["avg_rate"] == 16

def test_competition_other_small():
    ann = {"region": "부산", "speculative_zone": "", "size": "소형"}
    result = scoring.estimate_competition(ann)
    assert result["avg_rate"] == 9

def test_competition_large_no_cutoff():
    ann = {"region": "서울", "speculative_zone": "N", "size": "대형"}
    result = scoring.estimate_competition(ann)
    assert result["avg_cutoff_score"] is None
    assert "추첨제" in result["note"]

def test_competition_empty_size_defaults_medium():
    ann = {"region": "서울", "speculative_zone": "N", "size": ""}
    result = scoring.estimate_competition(ann)
    assert result["avg_rate"] == scoring._COMPETITION_STATS["서울_N_중형"][0]

def test_competition_has_disclaimer():
    result = scoring.estimate_competition({"region": "서울"})
    assert "disclaimer" in result
    assert len(result["disclaimer"]) > 0
