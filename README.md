# k-apt-alert

한국 청약 공고 알리미 — Claude Code 스킬

공공데이터포털의 청약홈 분양정보 API를 프록시 서버 경유로 조회하여, 사용자가 **API 키 없이** 최신 청약 공고를 조회·분석·알림받을 수 있습니다.

## 구조

```
k-apt-alert/
├── korea-apt-alert/    ← Claude Code 스킬 (사용자가 설치)
│   └── SKILL.md
├── proxy/              ← 프록시 서버 (운영자가 배포)
│   ├── main.py
│   ├── config.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── crawlers/
└── render.yaml         ← Render 배포 설정
```

## 스킬 설치 (사용자)

```bash
# 스킬 폴더를 Claude Code 개인 스킬 디렉토리에 복사
cp -r korea-apt-alert ~/.claude/skills/

# 또는 프로젝트 스킬로 설치
cp -r korea-apt-alert .claude/skills/
```

설치 후 Claude Code에서 바로 사용:

```
/korea-apt-alert                     # 최신 청약 공고 전체 조회
/korea-apt-alert setup               # 개인 프로필 설정 (맞춤 추천)
/korea-apt-alert 서울 아파트           # 서울 APT만 필터링
/korea-apt-alert 내 조건에 맞는 청약    # 프로필 기반 맞춤 조회
/korea-apt-alert --notify             # 조회 후 Slack/Telegram 발송
```

## 개인화 프로필

`/korea-apt-alert setup`으로 프로필을 설정하면 맞춤 추천을 받을 수 있습니다.

| 항목 | 설명 | 용도 |
|------|------|------|
| 출생연도 | 만 나이 계산 | 청약 자격 (만 19세+) |
| 선호 지역 | 복수 선택 | 지역 필터링 |
| 가구 구성 | 1인/신혼/기혼+자녀 등 | 특별공급 자격 판정 |
| 무주택 여부 | 본인 명의 주택 유무 | 대부분의 청약 자격 요건 |
| 청약통장 | 보유 여부 + 가입기간 | APT/LH 자격 + 가점 |
| 연소득 | 구간 선택 | LH/공공임대 소득 기준 |
| 선호 평형 | 소형/중형/대형 | 평형 필터링 |

프로필은 `~/.config/k-skill/apt-alert-profile.json`에 로컬 저장되며 서버로 전송되지 않습니다.

## 알림 설정 (선택)

Slack 또는 Telegram으로 알림을 받으려면 `~/.config/k-skill/secrets.env`에 추가:

```env
# Slack (하나 이상)
KSKILL_APT_SLACK_WEBHOOK=https://hooks.slack.com/services/T.../B.../xxx

# Telegram
KSKILL_APT_TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
KSKILL_APT_TELEGRAM_CHAT_ID=-1001234567890
```

알림 미설정 시에도 터미널에서 조회·분석은 정상 동작합니다.

## 데이터 소스

| 카테고리 | 데이터 출처 | 업데이트 주기 |
|----------|------------|--------------|
| APT 일반분양 | 청약홈 API | 월 25일 배치 |
| 오피스텔/도시형 | 청약홈 API | 실시간 |
| LH 공공분양 | LH 공지 API | 실시간 |
| APT 잔여세대 | 청약홈 API | 실시간 |
| 공공지원민간임대 | 청약홈 API | 실시간 |
| 임의공급 | 청약홈 API | 실시간 |

## 프록시 서버 (운영자용)

프록시 서버를 직접 배포하려면:

### 로컬 실행

```bash
cd proxy
pip install -r requirements.txt
DATA_GO_KR_API_KEY=your_key uvicorn main:app --reload
# http://localhost:8000/docs 에서 API 문서 확인
```

### Render 배포

1. GitHub에 이 레포를 push
2. Render Dashboard → New Web Service → Connect repo
3. Environment Variable에 `DATA_GO_KR_API_KEY` 추가
4. 배포 완료 후 SKILL.md의 프록시 URL을 업데이트

`DATA_GO_KR_API_KEY`는 [공공데이터포털](https://www.data.go.kr/)에서 무료 발급 가능합니다.
"한국부동산원_청약홈 분양정보 조회 서비스" 활용 신청 필요.

## 프록시 API

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /health` | 서버 상태 확인 |
| `GET /v1/apt/announcements` | 청약 공고 조회 |
| `GET /v1/apt/categories` | 조회 가능한 카테고리 목록 |

**쿼리 파라미터** (`/v1/apt/announcements`):

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `category` | `all` | `all`, `apt`, `officetell`, `lh`, `remndr`, `pbl_pvt_rent`, `opt` |
| `active_only` | `true` | 접수 마감 전 공고만 |
| `months_back` | `2` | 조회 기간 (1~12개월) |
| `region` | (전체) | 지역 필터 (쉼표 구분, 예: `서울,경기,인천`) |

## License

MIT
