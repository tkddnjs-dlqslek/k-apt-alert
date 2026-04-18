# korea-apt-alert

> 한국 청약 공고를 개인 프로필 기반으로 조회·분석하고 Slack/Telegram으로 알림받는 Agent Skill. **Claude Code · OpenAI Codex 둘 다 지원.**

- **무엇인가**: **APT 일반분양 · 오피스텔/도시형 · LH 공공분양 · APT 잔여세대 · 공공지원민간임대 · 임의공급** 6개 공공 API를 통합 조회하는 Agent Skill. Claude Code 또는 Codex CLI 대화창에 "내 조건에 맞는 청약 알려줘"라고 쓰면 바로 답합니다.
- **누가 쓰나**: 청약 준비 중인 개인(자격·가점 확인용), 부동산 관련 정보를 자동화하고 싶은 개발자
- **얼마나 걸리나**: 설치 2분, 프로필 설정 3분, 첫 조회 5초(캐시 히트 기준)

## 지원 런타임 — Claude Code 또는 Codex CLI

이 스킬은 YAML frontmatter + Markdown 기반 Agent Skill 표준을 따르므로 **두 런타임에서 동일하게 동작**합니다.

- **Anthropic Claude Code**: [claude.com/claude-code](https://claude.com/claude-code) · [docs](https://docs.claude.com/en/docs/claude-code/overview)
- **OpenAI Codex CLI**: [developers.openai.com/codex](https://developers.openai.com/codex) · [Skills 문서](https://developers.openai.com/codex/skills)

둘 다 macOS / Linux / Windows (PowerShell 또는 WSL) 지원. 설치 위치만 다르고 SKILL.md는 동일합니다.

## Prerequisites

| 항목 | 필요 여부 | 비고 |
|------|-----------|------|
| Claude Code **또는** Codex CLI | **둘 중 하나 필수** | 본 스킬이 동작하는 런타임 |
| 운영체제 | macOS / Linux / Windows 10+ | Windows는 PowerShell 또는 WSL |
| Python·Node 등 런타임 | ❌ 불필요 | 스킬 동작에는 필요 없음 (프록시 자체 호스팅 시에만 Python 3.11+) |
| 공공데이터포털 API 키 | ❌ 불필요 | 공용 프록시가 관리 |
| Slack/Telegram 계정 | 선택 | 알림 발송 시에만 필요 |

---

공공데이터포털 청약홈 분양정보 API 6종을 프록시 서버 경유로 통합 조회합니다. 사용자는 **API 키 없이** 최신 공고를 받아볼 수 있고, 개인 프로필을 등록하면 가점 추정·특별공급 자격·추천 유형까지 맞춤 분석됩니다.

## 어떤 걸 할 수 있나

| 기능 | 설명 | 로그인 필요 |
|------|------|-------------|
| 최신 공고 조회 | APT 일반분양·오피스텔·LH·잔여세대·공공지원민간임대·임의공급 6종 통합 | ❌ |
| 지역·구/군 필터 | 서울·경기·인천 등 17개 광역 + 세부 구/군 | ❌ |
| 프로필 기반 맞춤 추천 | 청약통장·무주택 여부·소득 구간 기준 자격 매칭 | ❌ (로컬 저장) |
| 추정 가점 계산 | 무주택 기간 + 부양가족 + 통장 가입기간 → 84점 만점 | ❌ |
| 특별공급 자격 판정 | 신혼부부·생애최초·다자녀·한부모·노부모 | ❌ |
| 가점대별 전략 안내 | 20점 미만 → 오피스텔 권장, 60+ → 수도권 도전 등 | ❌ |
| D-day 알림 | 마감 임박(D-3/D-1) / 당첨자 발표 / 계약 체결 | ❌ |
| 즐겨찾기 공고 | 관심 공고 저장 + 상태 변동 추적 | ❌ |
| 중복 알림 방지 | 7일 이내 발송 공고 자동 제외 | ❌ |
| Slack·Telegram 발송 | Block Kit 포맷 + 긴급도 이모지 | Slack/Telegram 계정 |
| 인접 지역 확장 | 매칭 0건이면 인접 도/광역 제안 (17개 매핑) | ❌ |
| 세대수·시공사 필터 | 대단지·1군 브랜드 필터 | ❌ |

## 처음 시작하는 순서

### 1단계: 스킬 설치

먼저 이 레포를 clone:
```bash
git clone https://github.com/tkddnjs-dlqslek/k-apt-alert.git
cd k-apt-alert
```

사용 중인 런타임에 맞게 설치하세요. **둘 다 설치해도 OK** (Claude Code·Codex 모두에서 사용 가능).

#### A) Claude Code — macOS / Linux / WSL
```bash
# 개인 스킬 디렉토리 (전역)
mkdir -p ~/.claude/skills && cp -r korea-apt-alert ~/.claude/skills/

# 또는 현재 프로젝트 한정
mkdir -p .claude/skills && cp -r korea-apt-alert .claude/skills/
```

#### A) Claude Code — Windows PowerShell
```powershell
# 개인 스킬 디렉토리 (전역)
$dst = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Recurse -Force korea-apt-alert $dst

# 또는 현재 프로젝트 한정
New-Item -ItemType Directory -Force -Path ".claude\skills" | Out-Null
Copy-Item -Recurse -Force korea-apt-alert ".claude\skills"
```

#### B) Codex CLI — macOS / Linux / WSL
```bash
# 개인 스킬 디렉토리 (전역)
mkdir -p ~/.agents/skills && cp -r korea-apt-alert ~/.agents/skills/

# 또는 현재 프로젝트 한정
mkdir -p .agents/skills && cp -r korea-apt-alert .agents/skills/
```

#### B) Codex CLI — Windows PowerShell
```powershell
# 개인 스킬 디렉토리 (전역)
$dst = "$env:USERPROFILE\.agents\skills"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Recurse -Force korea-apt-alert $dst

# 또는 현재 프로젝트 한정
New-Item -ItemType Directory -Force -Path ".agents\skills" | Out-Null
Copy-Item -Recurse -Force korea-apt-alert ".agents\skills"
```

#### C) 둘 다 사용 — Unix 심볼릭 링크 (선택)
파일 1벌만 유지하려면:
```bash
# Claude Code 경로에 실제 설치
mkdir -p ~/.claude/skills && cp -r korea-apt-alert ~/.claude/skills/
# Codex는 그 위치를 심볼릭 링크
mkdir -p ~/.agents/skills && ln -s ~/.claude/skills/korea-apt-alert ~/.agents/skills/korea-apt-alert
```

### 설치 검증

런타임을 재시작하고 대화창에서 아래 명령이 동작하면 성공입니다.
```
/korea-apt-alert 청약이 뭐야?
```
→ 초보 가이드·핵심 용어 사전이 응답으로 나오면 스킬이 정상 로드된 것입니다. Claude Code와 Codex 모두 동일한 결과가 나와야 합니다.

### 2단계: 프로필 설정 (선택이지만 강력 권장)

Claude Code에서:
```
/korea-apt-alert setup
```
대화형으로 출생연도·선호 지역·가구 구성·청약통장·연소득 등 12개 항목을 입력합니다.
프로필은 `~/.config/k-skill/apt-alert-profile.json`에 로컬 저장되며 서버로 전송되지 않습니다.

### 3단계: 조회

```
/korea-apt-alert                     # 전체 조회
/korea-apt-alert 내 조건에 맞는 청약    # 프로필 기반 맞춤
/korea-apt-alert 서울 강남구 대단지만   # 지역 + 구/군 + 필터
/korea-apt-alert 내 가점 몇 점이야?    # 추정 가점 + 전략 안내
/korea-apt-alert 청약이 뭐야?          # 초보 가이드
```

### 4단계: 알림 설정 (선택)

Slack/Telegram으로 정기 알림을 받으려면 `~/.config/k-skill/secrets.env`에 추가:

```env
KSKILL_APT_SLACK_WEBHOOK=https://hooks.slack.com/services/T.../B.../xxx
KSKILL_APT_TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
KSKILL_APT_TELEGRAM_CHAT_ID=-1001234567890
```

### 5단계: 자동 알림 (선택)

두 가지 옵션:

**(A) Claude Code `/loop` — 세션 내 반복**
```
/loop 24h /korea-apt-alert 내 조건에 맞는 청약 알림 보내줘
```

**(B) 프록시 notify API — 세션 불필요, 가장 안정적**

GitHub Actions·cron 등에서 매일 호출:
```bash
curl -X POST "https://k-apt-alert-proxy.onrender.com/v1/apt/notify?webhook_url=...&region=서울,경기,인천&reminder=d3"
```

📘 **자동화 전체 가이드**: [`examples/user-automation/`](./examples/user-automation/) — 본인 GitHub 계정에 **빈 repo 1개 + yaml 파일 1개**만 올리면 매일 오전 7시(KST) 자동 발송 (Fork 불필요, 5분 셋업)

## 실제 출력 예시

### 예시 1) `/korea-apt-alert 내 조건에 맞는 청약` (프로필 28세·서울·통장 3년)

```
📋 프로필: 만 28세 / 서울·경기·인천 / 1인 가구 / 무주택 / 통장 3년
📊 추정 가점: 11점 / 84점
   - 무주택 기간: 0점 (만 30세 미만, 혼인 이력 없음)
   - 부양가족: 5점 (0명)
   - 통장 가입기간: 6점 (3년)
⭐ 특별공급: 생애최초 (통장 2년+ 충족)

⚠️ 가점이 낮아 수도권 APT 가점제 당첨은 현실적으로 어렵습니다.
   오피스텔·잔여세대·임의공급, 지방 중소도시 APT, 특별공급이 더 유리합니다.

🎯 추천 Top 3:
  1. 오피스텔/도시형 — 가점 무관, 통장 불필요
  2. APT 잔여세대 — 무순위 추첨, 즉시 신청 가능
  3. 생애최초 특별공급 — 통장 2년 + 무주택 + 소득 충족

📌 접수 중 공고 (서울·경기·인천, 3건):
| 이름                  | 지역       | D-day | 세대수 | 타입   |
|---------------------|-----------|-------|-------|--------|
| 인천가정2지구 B2블록   | 인천 서구   | D-13  | 308   | APT    |
| 동탄 그웬 160         | 경기 화성   | D-12  | 160   | APT    |
| 용인 고림 동문 디 이스트 | 경기 처인구 | D-5   | 350   | APT    |

💡 다음 단계:
1. 관심 공고의 청약홈 원문을 확인하세요
2. 청약 일정: 특별공급 → 1순위 → 2순위
3. 당첨자 발표: 접수 마감 후 7~10일
```

### 예시 2) `/korea-apt-alert 청약이 뭐야?`

```
청약이란?
새로 짓는 아파트(신축)를 분양받기 위해 신청하는 제도입니다.
추첨 또는 가점(점수) 방식으로 당첨자를 선정하며, 당첨되면 시세보다
저렴하게 내 집을 마련할 수 있습니다.

핵심 용어 사전
| 용어         | 뜻 |
|------------|-----|
| 청약통장     | 청약 신청에 필요한 전용 저축 통장 ... |
| 가점제       | 무주택 기간 + 부양가족 + 통장 기간으로 ... |
| 추첨제       | 가점 무관, 무작위 추첨 ... |
| 특별공급     | 신혼부부·다자녀 등 별도 물량 ... |
...
```

### 예시 3) 매칭 0건 — 인접 지역 제안

```
⚠️ 광주 지역 현재 접수 중인 공고 0건입니다.
💡 인접 지역(전남·전북)으로 확장하시겠어요?
   "전남 포함해서 다시 찾아줘"라고 말씀해주세요.
```

---

## 포함된 기능

### 스킬 (사용자가 설치)
- [`korea-apt-alert/SKILL.md`](korea-apt-alert/SKILL.md) — 전체 워크플로우, 프로필 스키마, 자격 매칭 로직, 가점 계산, Top 3 추천, D-day, 인접 지역 확장 등

### 프록시 서버 (운영자가 배포)
- [`proxy/main.py`](proxy/main.py) — FastAPI 엔드포인트
- [`proxy/crawlers/`](proxy/crawlers/) — 6종 공공데이터포털 API 크롤러
- [`.github/workflows/warmup.yml`](.github/workflows/warmup.yml) — Render 슬립 방지 cron (12분 간격)
- [`.github/workflows/test.yml`](.github/workflows/test.yml) — mock 테스트 + E2E CI

### 페르소나 E2E 테스트
- [`test_personas.py`](test_personas.py) — 8명 시나리오 + mock 테스트 (무주택 기간, 통장 미성년 상한, LH 전국 공고, D-day 정렬)

## 프록시 API

**운영 중**: https://k-apt-alert-proxy.onrender.com

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /health` | 서버 상태 확인 (warmup용) |
| `GET /v1/apt/categories` | 카테고리 6종 목록 |
| `GET /v1/apt/announcements` | 청약 공고 조회 |
| `POST /v1/apt/notify` | Slack Webhook 발송 |
| `GET /v1/apt/cache` | 캐시·일일 호출 카운터 상태 (디버그) |

**쿼리 파라미터** (`/v1/apt/announcements`, `/v1/apt/notify` 공통):

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `category` | `all` | `all`, `apt`, `officetell`, `lh`, `remndr`, `pbl_pvt_rent`, `opt` |
| `active_only` | `true` | 접수 마감 전 공고만 (클라이언트 필터) |
| `months_back` | `2` | 조회 기간 (1~12개월) |
| `region` | (전체) | 지역 필터 (쉼표 구분, 예: `서울,경기`) |
| `district` | (전체) | 세부 지역 필터 (구/군 쉼표 구분) |
| `min_units` | `0` | 최소 세대수 (대단지만) |
| `constructor_contains` | (전체) | 시공사 키워드 (쉼표 구분) |
| `exclude_ids` | (전체) | 제외할 공고 ID (중복 방지) |
| `reminder` | (없음) | `d3` / `d1` / `winners` / `contract` |

### 데이터 소스

| 카테고리 | 업데이트 | 캐시 TTL |
|----------|---------|----------|
| APT 일반분양 | 월 25일 배치 | 60분 |
| 공공지원민간임대 | 실시간 | 30분 |
| 오피스텔/도시형, LH, 잔여세대, 임의공급 | 실시간 | 10분 |

## 프록시 서버 (운영자용)

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
3. Environment Variable 등록:
   - `DATA_GO_KR_API_KEY` (필수) — [공공데이터포털](https://www.data.go.kr/) 무료 발급
   - `SENTRY_DSN` (선택) — 에러 모니터링

### 운영 보호 장치
- **병렬 fetch**: 6개 카테고리 동시 크롤링 (ThreadPoolExecutor)
- **카테고리별 TTL**: apt 60분 / pbl_pvt_rent 30분 / 나머지 10분
- **Stale fallback**: fetch 실패 시 만료된 캐시라도 반환 (가용성 우선)
- **일일 rate limit**: 9000건 초과 시 stale 캐시만 반환
- **12분 간격 warmup**: Render free tier 슬립 방지

## 보안·프라이버시

- 프로필은 로컬 파일(`~/.config/k-skill/*.json`)에 저장되며 **프록시·서버로 전송되지 않습니다**.
- 프록시 요청에는 지역·평형·카테고리·세대수·시공사 키워드만 포함됩니다 (개인정보 미포함).
- Unix/macOS는 `chmod 600`이 자동 설정됩니다.
- 프로필 삭제: `/korea-apt-alert profile --delete` 또는 파일 직접 삭제.

## FAQ

**Q. 프록시 서버가 응답하지 않아요**
A. Render free tier는 15분 비활성 시 슬립합니다. warmup cron이 12분 간격으로 핑을 보내지만, 자정~새벽 등은 슬립 상태일 수 있습니다. 첫 호출이 30초~2분 걸릴 수 있습니다.

**Q. 가점 계산이 정확한가요?**
A. 프로필 기반 추정치입니다. 만 30세 ↔ 혼인신고일 중 늦은 해 기산, 통장 미성년 가입분 최대 2년 인정 등 주요 규칙은 반영되어 있지만, 부양가족 직계존속 3년 동일 세대 등록 요건은 자동 확인이 불가합니다. 정확한 가점은 [청약홈](https://www.applyhome.co.kr)에서 조회하세요.

**Q. 1주택자도 사용할 수 있나요?**
A. 네. 오피스텔, 잔여세대, 임의공급은 무주택 불문이며, "갈아타기 안내"가 자동 제공됩니다.

**Q. LH 공고의 지역이 "전국"으로 나와요**
A. LH 공고 제목에서 특정 지역을 추론할 수 없는 경우 "전국"으로 표시되며, 모든 프로필 지역 필터에서 항상 통과됩니다.

**Q. 매칭 공고가 0건이에요**
A. 프로필 지역이 좁은 경우 인접 지역(17개 매핑) 확장 제안을 받습니다. 예: 광주 → 전남·전북, 강원 → 충북.

## License

MIT
