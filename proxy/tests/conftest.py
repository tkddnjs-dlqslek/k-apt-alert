"""pytest 공통 설정 — `live` 마커 등록 + sys.path 보정 + 환경 초기화.

config.py가 import 시점에 DATA_GO_KR_API_KEY를 frozen하므로,
어떤 테스트 모듈보다도 먼저 환경변수를 설정해 모든 import에서 동일한 값이 보이도록 한다.
"""

import os
import sys
from pathlib import Path

# 1) 가장 먼저 환경변수 set — 어떤 모듈 import보다도 우선
os.environ.setdefault("DATA_GO_KR_API_KEY", "test-key")

# 2) proxy/ 디렉토리를 import path에 추가
PROXY_ROOT = Path(__file__).resolve().parent.parent
if str(PROXY_ROOT) not in sys.path:
    sys.path.insert(0, str(PROXY_ROOT))

# 3) config.py가 다른 테스트에서 먼저 import돼 비어있을 수 있으므로 강제 동기화
import config as _config  # noqa: E402

if not _config.DATA_GO_KR_API_KEY:
    _config.DATA_GO_KR_API_KEY = "test-key"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: 실 네트워크가 필요한 회귀 테스트 — 기본 SKIP, `pytest -m live`로 실행",
    )


FIXTURES_DIR = Path(__file__).parent / "fixtures"


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def reset_dedup_store():
    """각 테스트 전후 in-memory dedup store 초기화 — 테스트 간 오염 방지."""
    import notified as _nd
    _nd.reset()
    yield
    _nd.reset()


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
    except ImportError:
        return
    monkeypatch.setattr(notice_raw, "_load_from_data_branch", lambda notice_id: None)
