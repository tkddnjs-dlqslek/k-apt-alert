import os

DATA_GO_KR_API_KEY = os.getenv("DATA_GO_KR_API_KEY", "")

API_REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2

_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"

# Detail APIs
APPLYHOME_API_URL = f"{_BASE}/getAPTLttotPblancDetail"
OFFICETELL_API_URL = f"{_BASE}/getUrbtyOfctlLttotPblancDetail"
REMNDR_API_URL = f"{_BASE}/getRemndrLttotPblancDetail"
PBL_PVT_RENT_API_URL = f"{_BASE}/getPblPvtRentLttotPblancDetail"
OPT_API_URL = f"{_BASE}/getOPTLttotPblancDetail"

# Mdl (size detail) APIs
APPLYHOME_MDL_API_URL = f"{_BASE}/getAPTLttotPblancMdl"
OFFICETELL_MDL_API_URL = f"{_BASE}/getUrbtyOfctlLttotPblancMdl"
REMNDR_MDL_API_URL = f"{_BASE}/getRemndrLttotPblancMdl"
PBL_PVT_RENT_MDL_API_URL = f"{_BASE}/getPblPvtRentLttotPblancMdl"
OPT_MDL_API_URL = f"{_BASE}/getOPTLttotPblancMdl"

# 청약 결과 API (당첨자 선정 결과 조회)
APPLYHOME_RSFL_API_URL = f"{_BASE}/getAPTRsflInfo"

LH_NOTICE_API_URL = "http://apis.data.go.kr/B552555/lhNoticeInfo1/getNoticeInfo1"

# Notice raw extraction (Phase 1 of notice-interpreter)
NOTICE_RAW_TTL = 7 * 24 * 3600  # 7일 — 모집공고문은 사실상 변경 없음, 정정공고는 force_refresh로 우회
NOTICE_RAW_DAILY_LIMIT_FREE = 1000
NOTICE_RAW_HTTP_TIMEOUT = 15
TIER_LIMITS = {"free": 30000, "paid": 80000}
NOTICE_MAX_CHARS_DEFAULT = 30000
NOTICE_SUPPORTED_HOSTS = ("applyhome.co.kr", "apply.lh.or.kr", "i-sh.co.kr", "gh.or.kr")
