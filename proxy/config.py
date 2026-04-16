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

LH_NOTICE_API_URL = "http://apis.data.go.kr/B552555/lhNoticeInfo1/getNoticeInfo1"
