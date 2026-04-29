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
