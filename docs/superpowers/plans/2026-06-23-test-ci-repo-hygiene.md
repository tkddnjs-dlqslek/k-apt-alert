# 테스트 정상화 + CI 안전망 + 레포 위생 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 깨진 pytest 21건을 고치고, CI가 pytest를 실제로 돌리게 만들어 회귀 안전망 구멍을 막고, working dir의 스크래치 파일을 정리한다.

**Architecture:** 라이브 프록시·자동화는 정상. 실패는 전부 *stale 테스트*(코드가 최신 기능으로 진화했는데 테스트가 옛 동작을 단언)다. 코드는 건드리지 않고 테스트만 현 동작에 맞춘다. 그 뒤 `test.yml`에 pytest 잡을 추가해 같은 구멍이 재발하지 않게 한다.

**Tech Stack:** Python 3.12, pytest, FastAPI TestClient, GitHub Actions

## Global Constraints

- production 코드(`proxy/crawlers/notice_raw.py`, `proxy/main.py`)는 수정 금지 — 테스트/CI/위생만 손댄다.
- 테스트는 실 네트워크 없이 통과해야 한다 (`requests`는 항상 목킹/차단).
- 작업 디렉토리: `C:\Users\user\Desktop\k-apt-alert`. pytest는 `proxy/`에서 실행.
- 커밋은 작업 단위로 자주.

---

### Task 1: notice_raw 테스트 18건 — data-branch 캐시 경로 차단

**과거 문제:** `extract_notice_raw()`에 `_load_from_data_branch()`(data 브랜치 영속 캐시, 신규 기능)가 추가됐다. 이 함수는 `requests.get(...).json()`을 호출하는데, 테스트가 `requests.get`을 HTML용으로 목킹하면서 `.json()`이 Mock을 반환 → `warmed.get("text")`가 truthy Mock → `full_text`로 새어들어 `len(Mock)`에서 `TypeError`.

**현재 수정:** conftest에 autouse fixture를 추가해 모든 테스트에서 data-branch 로드를 `None`으로 차단(= HTML 추출 경로 강제). 차단된 경로를 위한 양성 테스트 1건을 별도로 추가해 커버리지 유지.

**Files:**
- Modify: `proxy/tests/conftest.py`
- Test: `proxy/tests/test_notice_raw.py` (양성 테스트 1건 추가)

**Interfaces:**
- Consumes: `crawlers.notice_raw._load_from_data_branch(notice_id: str) -> dict | None`, `crawlers.notice_raw.extract_notice_raw(notice_id, url, max_chars, force_refresh=False) -> dict`
- Produces: (없음 — 테스트 전용 변경)

- [ ] **Step 1: 회귀 확인 — 현재 실패 재현**

Run: `cd proxy && python -m pytest tests/test_notice_raw.py -q`
Expected: 다수 FAIL — `TypeError: object of type 'Mock' has no len()`

- [ ] **Step 2: conftest에 data-branch 차단 fixture 추가**

`proxy/tests/conftest.py` 끝에 추가:

```python
@pytest.fixture(autouse=True)
def disable_notice_data_branch(monkeypatch):
    """notice_raw의 data 브랜치 영속 캐시를 단위 테스트에서 차단.

    _load_from_data_branch는 requests.get().json()을 호출하므로, HTML용으로
    목킹된 requests.get이 새어들어 full_text에 Mock이 들어간다. 단위 테스트는
    HTML 추출 경로만 검증하므로 항상 None을 반환시켜 그 경로를 강제한다.
    data 브랜치 hit 경로는 test_data_branch_cache_hit에서 명시적으로 재패치해 검증.
    """
    try:
        from crawlers import notice_raw
    except Exception:
        return
    monkeypatch.setattr(notice_raw, "_load_from_data_branch", lambda notice_id: None)
```

- [ ] **Step 3: data-branch hit 양성 테스트 추가 (커버리지 보전)**

`proxy/tests/test_notice_raw.py` 끝에 추가:

```python
def test_data_branch_cache_hit(monkeypatch):
    warmed = {
        "url": "https://www.applyhome.co.kr/x",
        "source": "html",
        "title": "워밍된 공고",
        "text": "워밍된 본문 텍스트입니다.",
        "sections": {},
        "has_pdf": False,
    }
    monkeypatch.setattr(notice_raw, "_load_from_data_branch", lambda notice_id: warmed)
    # requests.get이 호출되면 안 됨 — 호출되면 data-branch 경로를 안 탔다는 뜻
    def _boom(*a, **kw):
        raise AssertionError("data-branch hit이면 네트워크 fetch 금지")
    monkeypatch.setattr(notice_raw.requests, "get", _boom)

    out = notice_raw.extract_notice_raw(
        "apt_warm", "https://www.applyhome.co.kr/x", 30000
    )
    assert out["text"] == "워밍된 본문 텍스트입니다."
    assert out["title"] == "워밍된 공고"
    assert out["truncated"] is False
```

- [ ] **Step 4: 통과 확인**

Run: `cd proxy && python -m pytest tests/test_notice_raw.py -q`
Expected: PASS (양성 테스트 포함 전부 통과, `Mock has no len()` 소멸)

- [ ] **Step 5: 커밋**

```bash
git add proxy/tests/conftest.py proxy/tests/test_notice_raw.py
git commit -m "test(notice_raw): data 브랜치 캐시 경로 차단 fixture + hit 양성 테스트"
```

---

### Task 2: notify 테스트 3건 — 채널 라벨 포맷 변경 반영

**과거 문제:** 멀티채널 기능 도입으로 채널 라벨이 `"slack"` → `"slack:{webhook 끝 6자}"`(예: `slack:x`)로 바뀌었다(SKILL.md에 문서화된 동작). 테스트는 옛 `"slack"` 정확 일치를 단언해 실패.

**현재 수정:** `_short_hook_label` 내부 구현에 결합되지 않도록 **prefix 매칭**(`startswith("slack")`)으로 단언을 바꾼다.

**Files:**
- Test: `proxy/tests/test_main_endpoints.py` (3개 테스트 단언 수정)

**Interfaces:**
- Consumes: `POST /v1/apt/notify` 응답 `{"channels": list[str], "errors": dict|None, "sent": int}` — slack 채널 라벨은 `"slack:<6자>"`, telegram은 `"telegram"`.
- Produces: (없음)

- [ ] **Step 1: 회귀 확인**

Run: `cd proxy && python -m pytest tests/test_main_endpoints.py -k notify -q`
Expected: `test_notify_slack_success`, `test_notify_dual_channel`, `test_notify_partial_failure_one_channel_succeeds` FAIL

- [ ] **Step 2: `test_notify_slack_success` 단언 수정**

`proxy/tests/test_main_endpoints.py:203` 한 줄 교체:

```python
    assert any(c.startswith("slack") for c in body["channels"])
```

- [ ] **Step 3: `test_notify_dual_channel` 단언 수정**

`proxy/tests/test_main_endpoints.py:228` 한 줄 교체:

```python
    chans = resp.json()["channels"]
    assert any(c.startswith("slack") for c in chans) and "telegram" in chans
```

- [ ] **Step 4: `test_notify_partial_failure_one_channel_succeeds` 단언 수정**

`proxy/tests/test_main_endpoints.py:250` 한 줄 교체 (errors 키도 `slack:<6자>` 라벨이므로 prefix 매칭):

```python
    assert any(k.startswith("slack") for k in body["errors"])
```

- [ ] **Step 5: 통과 확인**

Run: `cd proxy && python -m pytest tests/test_main_endpoints.py -k notify -q`
Expected: PASS

- [ ] **Step 6: 전체 스위트 green 확인**

Run: `cd proxy && python -m pytest -q`
Expected: `0 failed` (직전 `21 failed, 176 passed, 1 skipped` → 전부 통과 + 신규 1건)

- [ ] **Step 7: 커밋**

```bash
git add proxy/tests/test_main_endpoints.py
git commit -m "test(notify): 멀티채널 라벨(slack:<6자>) 포맷에 맞춰 단언 prefix 매칭으로 수정"
```

---

### Task 3: CI에 pytest 잡 추가 — 안전망 구멍 차단

**과거 문제:** `.github/workflows/test.yml`은 `main.py` syntax check + `test_personas.run_mock_tests()`만 돌린다. `proxy/tests/`의 198개 pytest는 CI 밖이라, 21건이 깨져도 main이 계속 green이었다.

**현재 수정:** `mock-tests` 잡에 의존성 설치 + `pytest proxy/tests` 스텝을 추가해 매 push/PR마다 단위 테스트가 실제로 돈다.

**Files:**
- Modify: `.github/workflows/test.yml`
- Reference: `proxy/requirements.txt`, `proxy/requirements-dev.txt`

**Interfaces:**
- Consumes: `proxy/tests/` (Task 1·2 이후 green 상태), `proxy/requirements-dev.txt`(pytest 포함 가정)
- Produces: CI 잡 `pytest-suite`

- [ ] **Step 1: requirements-dev.txt에 pytest 존재 확인**

Run: `grep -i pytest proxy/requirements-dev.txt`
Expected: `pytest` 라인 출력. 없으면 `pytest` 한 줄 추가 후 커밋에 포함.

- [ ] **Step 2: `test.yml`에 pytest 잡 추가**

`.github/workflows/test.yml`의 `mock-tests` 잡 아래(같은 들여쓰기 레벨, `e2e-tests` 위)에 삽입:

```yaml
  pytest-suite:
    name: Pytest unit suite (network-free)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: |
          pip install -r proxy/requirements.txt
          pip install -r proxy/requirements-dev.txt
      - name: Run pytest
        working-directory: proxy
        run: python -m pytest -q
```

- [ ] **Step 3: 로컬에서 CI와 동일 명령 검증**

Run: `cd proxy && python -m pytest -q`
Expected: `0 failed`

- [ ] **Step 4: 커밋 + 푸시 후 CI 확인**

```bash
git add .github/workflows/test.yml proxy/requirements-dev.txt
git commit -m "ci: pytest 단위 스위트를 test.yml에 연결 — 회귀 안전망 구멍 차단"
```
푸시 후: `gh run list --workflow=test.yml --limit 1` → `pytest-suite` 잡 success 확인.

---

### Task 4: 스크래치 파일 59개 정리 + .gitignore 마무리

**과거 문제:** working dir에 디버그 잔여물 59개(`_*.json`, `_*.html`, `*.ts` 중복본 `my-score-v2/v3/fix.ts` 등, `validate_*.py`, `gh_test.json`)가 떠 있고, `.gitignore`에 `stress_runner.py` 추가가 미커밋 상태.

**현재 수정:** untracked 스크래치를 삭제하고(추적 파일은 절대 건드리지 않음), `.gitignore` 변경을 커밋. 삭제 전 목록을 눈으로 확인한다.

**Files:**
- Modify: `.gitignore`
- Delete: untracked 스크래치 파일들 (아래 Step에서 목록 확인 후)

- [ ] **Step 1: 삭제 대상(untracked만) 목록 확인**

Run: `git status --porcelain | grep '^??'`
Expected: `_*.json`, `_*.html`, `_dl.bin`, `*_test.json`, 루트 `*.ts`, `validate_*.py`, `SKILL_*.md`, `LINKEDIN_POST_V*.md`, `README_fix.md`, `013_patches.sql`, `migrate_secrets.sh` 등. **추적 파일(`M`)은 목록에 없어야 함.**

- [ ] **Step 2: 백업 후 일괄 삭제**

```bash
mkdir -p ../_kapt_scratch_backup_20260623
git ls-files --others --exclude-standard -z | xargs -0 -I{} cp --parents {} ../_kapt_scratch_backup_20260623/ 2>/dev/null || true
git clean -fd --dry-run
```
`--dry-run` 출력에 `docs/`·`proxy/`·`skills/` 등 의도한 산출물이 섞이지 않았는지 확인.

- [ ] **Step 3: 실제 삭제 (dry-run 확인 후에만)**

```bash
git clean -fd
```
Expected: untracked 스크래치 제거. `git status -s`에 `?? ` 라인 소멸(또는 의도한 신규 파일만 남음).

- [ ] **Step 4: .gitignore 커밋**

```bash
git add .gitignore
git commit -m "chore: .gitignore에 stress_runner.py 추가 + 스크래치 파일 정리"
```

- [ ] **Step 5: 최종 상태 확인**

Run: `git status -s && cd proxy && python -m pytest -q`
Expected: working tree clean(또는 의도한 변경만), pytest `0 failed`.

---

## 실행 순서 메모

Task 1 → 2 → 3 은 의존(테스트 green이어야 CI 잡이 의미)이므로 순서대로. Task 4(위생)는 독립이라 언제든 가능.
