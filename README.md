# korea-apt-alert

> 한국 청약 공고를 개인 프로필 기반으로 조회·분석하고 Slack/Telegram으로 알림받는 Agent Skill. **Claude Code · OpenAI Codex 둘 다 지원.**

- **무엇인가**: **APT 일반분양 · 오피스텔/도시형 · LH 공공분양 · APT 잔여세대 · 공공지원민간임대 · 임의공급 · SH 서울공공주택 · GH 경기공공주택** 총 8개 채널을 통합 조회하는 Agent Skill. Claude Code 또는 Codex CLI 대화창에 "내 조건에 맞는 청약 알려줘"라고 쓰면 바로 답합니다.
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

> **신청만 빼고 다 해드립니다.** 청약 정보 발견부터 자격 판정·일정 관리·알림까지 전 과정 자동화.

### 📢 공고 발견·필터링
| 기능 | 설명 | 로그인 필요 |
|------|------|-------------|
| 8개 채널 통합 조회 | APT 일반·오피스텔·LH·잔여세대·공공지원민간임대·임의공급·**SH(서울)**·**GH(경기)** | ❌ |
| 지역·구/군 필터 | 17개 광역 + 세부 자치구 (강남구·송파구 등) | ❌ |
| 세대수·시공사 필터 | 대단지(500세대+)·1군 브랜드 키워드 | ❌ |
| 조회 기간 조절 | 최근 1~12개월 (`months_back`) | ❌ |
| 인접 지역 확장 | 매칭 0건이면 인접 도/광역 자동 제안 (17개 매핑) | ❌ |

### 📊 자격·가점 판정 (결정론 계산)
| 기능 | 설명 | 신규 |
|------|------|------|
| 가점 84점 만점 정확 계산 | 무주택(32) + 부양가족(35) + 통장(17) | |
| 미성년 통장 한도 자동 차감 | 2024.7.1. 시행 5년 / 그 이전 2년 | |
| **1순위 자격 판정** | 지역별 납입횟수 (투기과열 24회/수도권 12회/기타 6회) | ✨ |
| 특별공급 5종 자격 | 신혼부부·생애최초·다자녀·노부모부양·청년 | |
| 가점대별 전략 안내 | 20점 미만 → 오피스텔, 60+ → 수도권 도전 등 | |
| **공고-프로필 적합도 매칭** | `/v1/apt/match` → high/medium/low 3단계 | ✨ |
| 1주택자 갈아타기 안내 | 추첨제·잔여세대 경로 안내 | |
| 소득 자격 정성 판정 | 가구원수 × 도시근로자 평균소득 기준 | |

### 📄 공고 해석·매칭
| 기능 | 설명 | 신규 |
|------|------|------|
| **모집공고 원문 자동 추출** | 청약홈·LH·SH·GH 4개 사이트 본문 파싱 | ✨ |
| **섹션 자동 분리** | 자격·공급일정·공급금액·유의사항·공급대상 | ✨ |
| **LLM 기반 자연어 해석** | 자격 요건·일정·가격을 사용자 프로필 맥락에 맞춰 요약 | ✨ |

### 🎲 경쟁률 (3단 폴백)
| 단계 | 데이터 출처 | 정확도 |
|---|---|---|
| 1순위 | 청약홈 실제 결과 페이지 (마감·발표 끝난 공고) | 가장 정확 |
| 2순위 | 공공데이터포털 결과 API — 같은 지역 12개월 평균 | 참고 우수 |
| 3순위 | 2024-2025 통계 추정치 (서울 투기과열 소형 160:1 등) | 폴백 |

### 📅 일정 관리
| 기능 | 설명 | 신규 |
|------|------|------|
| D-day 자동 계산·색상 분기 | 🔴 D-1 이하 / 🟡 D-2~3 / 🟢 D-4+ | |
| **캘린더 ICS 다운로드** | 구글/아이폰/아웃룩 캘린더 즉시 임포트 | ✨ |
| 4종 리마인더 | D-3 임박 / D-1 초긴급 / 당첨발표 임박 / 계약 임박 | |

### 🔔 알림 발송
| 기능 | 설명 | 신규 |
|------|------|------|
| Slack Block Kit | 헤더·divider·section·버튼 풀 포맷 | |
| Telegram Bot | HTML parse_mode + 링크 미리보기 차단 | |
| 양 채널 동시 발송 | 한쪽 실패해도 다른쪽 정상 전달 | |
| 서버측 7일 자동 dedup | 같은 공고 중복 발송 차단 (`dedup=true` 기본) | |
| Webhook/Token 자동 감지·저장 | 채팅창 붙여넣기로 secrets.env 자동 갱신 | |

### 🆕 공고 변동 추적 (Phase 1)
| 기능 | 설명 |
|------|------|
| 매일 KST 08:00 자동 diff | GitHub Actions가 어제 ↔ 오늘 비교 |
| 신규/수정/삭제 분류 | `new` / `updated` (12개 추적 필드) / `removed` |
| since·change_type 필터 | 원하는 기간·종류만 조회 |
| 30일 이력 보관 | data 브랜치에 자동 누적, 자동 정리 |
| 부트스트랩 vs 정상 상태 구분 | 처음 사용자가 헷갈리지 않게 안내 |

### 🗺 입지 분석 (Apify Google Maps + WebSearch)
| 항목 | 출력 |
|------|------|
| 교통 | 가까운 지하철역 + 도보 시간 + 호선 |
| 학군 | 초·중·고 학교명 + 도보 시간 |
| 편의시설 | 대형마트 / 병원 / 공원 (반경 1.5km) |
| 지역 호재 | 교통(GTX 등) · 개발(산업단지) · 학군 평판 (WebSearch 기반) |
| 종합 평가 | 강점·약점 자동 정리 + ⚠️ 현장 답사 권고 |

> **사전 설정**: [Apify 커넥터](https://apify.com) 1회 등록 (월 $5 무료 크레딧 ≈ 100건). 미설정 시 WebSearch fallback (정확도 ↓).

### 👤 프로필·즐겨찾기
| 기능 | 설명 |
|------|------|
| 12개 항목 대화형 setup | 출생연도·지역·가구·통장·소득·평형 등 |
| 프로필 부분 업데이트 | "혼인신고일만 수정" 같은 자연어 요청 |
| 프로필 갱신 알림 | 90일·365일 경과 시 자동 |
| 즐겨찾기 공고 | 추가/제거/목록 + 변동 체크 |

### 🔄 자동 스케줄 (4가지 옵션)
| 옵션 | 설정 | 비고 |
|------|------|------|
| 즉시 1회 | `/korea-apt-alert 알림 보내줘` | 그 시점 1회만 |
| `/loop` | `/loop 24h /korea-apt-alert ...` | 세션 열어둔 동안 |
| **GitHub Actions** | `.yml` 1개 + Secrets 등록 | PC 꺼도 작동 ⭐ 권장 |
| 로컬 cron / Task Scheduler | macOS·Linux·Windows | PC 켜둔 동안 |

자연어 시간 입력(`"저녁 7시"`, `"주말만"`) → cron 자동 변환 지원.

### 🛡️ 운영 자동화
| 기능 | 주기 | 용도 |
|------|------|------|
| Render warmup | 12분마다 | 무료 티어 슬립 방지 |
| API 사용량 80% Gmail 알림 | KST 09:00 매일 | 한도 초과 사전 경고 |
| 변동 추적 diff | KST 08:00 매일 | 이력 자동 누적 |

## 처음 시작하는 순서

### 1단계: 설치

이 레포는 **Claude Code 플러그인** + **단독 스킬** 두 방식으로 설치할 수 있습니다. 스킬 본문(SKILL.md)은 [`skills/korea-apt-alert/SKILL.md`](skills/korea-apt-alert/SKILL.md) 한 곳에만 존재합니다 (단일 소스).

#### A) 플러그인으로 설치 (권장 — Claude Code)

스킬 + 자격 판별 에이전트(apt-eligibility) + MCP 서버를 한 번에 설치합니다.
```
/plugin marketplace add tkddnjs-dlqslek/k-apt-alert
/plugin install k-apt-alert@k-apt-alert-marketplace
```
MCP 서버는 로컬에서 `python3`로 기동됩니다 (Windows에서 `python3`이 안 잡히면 [`.mcp.json`](.mcp.json)의 `command`를 `python`으로 변경).

#### B) 단독 스킬 설치 (Claude Code 또는 Codex)

플러그인 없이 스킬만 쓰고 싶을 때. MCP 서버 대신 스킬이 프록시를 직접 호출합니다 (curl 폴백).

**Claude Code — macOS / Linux / WSL**
```bash
git clone https://github.com/tkddnjs-dlqslek/k-apt-alert.git /tmp/k-apt-alert \
  && mkdir -p ~/.claude/skills \
  && cp -r /tmp/k-apt-alert/skills/korea-apt-alert ~/.claude/skills/korea-apt-alert
```
**Claude Code — Windows PowerShell**
```powershell
git clone https://github.com/tkddnjs-dlqslek/k-apt-alert.git $env:TEMP\k-apt-alert
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse -Force "$env:TEMP\k-apt-alert\skills\korea-apt-alert" "$env:USERPROFILE\.claude\skills\korea-apt-alert"
```
**Codex CLI** — 위 명령에서 `~/.claude/skills` → `~/.agents/skills` (PowerShell은 `.claude` → `.agents`)로 바꾸면 됩니다.

> **중요:** 대상 폴더명을 `korea-apt-alert`로 유지해야 `/korea-apt-alert` 명령이 동작합니다 (SKILL.md의 스킬명과 일치 필요).
>
> **간단한 방법:** 에이전트에게 `https://github.com/tkddnjs-dlqslek/k-apt-alert` URL을 주고 "이 스킬 설치해줘"라고 하면 위 과정을 알아서 처리합니다.

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

GitHub Actions·cron 등에서 매일 호출 (한글 파라미터는 반드시 퍼센트 인코딩):
```bash
# region=서울,경기,인천 → 퍼센트 인코딩
curl -X POST "https://k-apt-alert-proxy.onrender.com/v1/apt/notify?webhook_url=...&region=%EC%84%9C%EC%9A%B8,%EA%B2%BD%EA%B8%B0,%EC%9D%B8%EC%B2%9C&reminder=d3"
```

📘 **자동화 전체 가이드**: [`examples/user-automation/`](./examples/user-automation/) — 본인 GitHub 계정에 **빈 repo 1개 + yaml 파일 1개**만 올리면 매일 오전 7시(KST) 자동 발송 (Fork 불필요, 5분 셋업)

## 실제 출력 예시

### 예시 1) `/korea-apt-alert 내 조건에 맞는 청약` (프로필 28세·서울·통장 3년)

```
📋 프로필: 만 28세 / 서울·경기·인천 / 1인 가구 / 무주택 / 통장 3년
📊 추정 가점: 10점 / 84점
   - 무주택 기간: 0점 (만 30세 미만, 혼인 이력 없음)
   - 부양가족: 5점 (0명)
   - 통장 가입기간: 5점 (3년 — 6개월 미만 1점 + 6~12개월 2점 + 1~2년 3점 + 2~3년 4점 + 3년 도래 시 5점)
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

### 플러그인 (Claude Code)
- [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) — 플러그인 매니페스트 (스킬·에이전트·MCP 서버 묶음)
- [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) — `/plugin marketplace add`로 설치 가능하게
- [`skills/korea-apt-alert/SKILL.md`](skills/korea-apt-alert/SKILL.md) — **스킬 본문 (단일 소스)**: 전체 워크플로우, 프로필 스키마, 자격 매칭, 가점 계산, Top 3 추천, D-day, 인접 지역 확장 등
- [`agents/apt-eligibility.md`](agents/apt-eligibility.md) — 가점·자격 판별 전담 서브에이전트 (결정론 계산은 `/v1/apt/score` 위임)
- [`mcp-server/server.py`](mcp-server/server.py) — 프록시를 MCP(stdio)로 노출하는 의존성 0 서버. 툴 7종 (search_announcements·list_categories·score_profile·get_notice_raw·get_changes·send_notification·get_competition)
- [`.mcp.json`](.mcp.json) — MCP 서버 기동 설정

### 프록시 서버 (운영자가 배포)
- [`proxy/main.py`](proxy/main.py) — FastAPI 엔드포인트 (15개 라우트)
- [`proxy/crawlers/`](proxy/crawlers/) — 8종 공공데이터/HTML 크롤러 (apt·officetell·lh·remndr·pbl_pvt_rent·opt·sh·gh·notice_raw·competition)
- [`proxy/scoring.py`](proxy/scoring.py) — 결정론 가점·1순위·특공·경쟁률 통계
- [`proxy/notified.py`](proxy/notified.py) — 서버측 7일 in-memory dedup
- [`proxy/changes.py`](proxy/changes.py) — 공고 변동 이력 캐시·필터링

### 자동화 워크플로
- [`.github/workflows/warmup.yml`](.github/workflows/warmup.yml) — Render 슬립 방지 + 캐시 prefetch (12분 cron, concurrency 적용)
- [`.github/workflows/changes-tracker.yml`](.github/workflows/changes-tracker.yml) — 매일 KST 08:00 공고 diff → data 브랜치
- [`.github/workflows/usage-check.yml`](.github/workflows/usage-check.yml) — 매일 KST 09:00 API 사용량 체크 + 80% 초과 시 Gmail
- [`.github/workflows/test.yml`](.github/workflows/test.yml) — mock 테스트 + E2E CI
- [`scripts/track_changes.py`](scripts/track_changes.py) — 일일 diff 스크립트

### 테스트
- `proxy/tests/` — pytest 53+ 케이스 (가점·1순위·경쟁률·notice_raw·main 헬퍼)

## 프록시 API

**운영 중**: https://k-apt-alert-proxy.onrender.com

### 사용자 대면 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|------|------|
| `/v1/apt/announcements` | GET | 8개 카테고리 통합 공고 조회 (전체 필터 지원) |
| `/v1/apt/score` | POST | 가점 + 1순위 자격 + 특별공급 자격 결정론 계산 |
| `/v1/apt/match` | POST | 공고-프로필 카테고리·지역·세대수 적합도 |
| `/v1/apt/notice/{id}/raw` | GET | 모집공고 원문 텍스트 추출 (LLM 해석용) |
| `/v1/apt/announcements/{id}/competition` | GET | 경쟁률 3단 폴백 조회 (`?history=true`) |
| `/v1/apt/announcements/{id}/ics` | GET | 청약 일정 ICS 캘린더 다운로드 |
| `/v1/apt/changes` | GET | 공고 변동 이력 조회 (since/change_type/limit) |
| `/v1/apt/notify` | POST | Slack/Telegram 동시 발송 (서버측 7일 dedup) |
| `/v1/apt/categories` | GET | 카테고리 8종 목록 |

### 디버그·운영 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|------|------|
| `/health` | GET | 서버 상태·API 키 설정 여부 |
| `/v1/apt/cache` | GET | 캐시·일일 호출 카운터·dedup 상태 |
| `/v1/apt/dedup/stats` | GET | dedup store 추적 항목 수 |
| `/v1/apt/dedup/reset` | POST | dedup store 전체 초기화 (운영자용) |
| `/v1/apt/notice/cache-status` | GET | notice_raw 캐시 상태 |
| `/v1/apt/changes/cache-status` | GET | changes 캐시 상태 |

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
| SH(서울) · GH(경기) 공공주택 | HTML 크롤링 | 30분 |

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
- **12분 간격 warmup (best-effort)**: Render free tier 슬립 방지 — 단 GitHub Actions free cron은 부하 시 5~30분 지연이 흔해서 일부 시간대(특히 자정~새벽)는 슬립 발생 가능

## 보안·프라이버시

- 프로필은 로컬 파일(`~/.config/k-skill/*.json`)에 저장되며 **프록시·서버로 전송되지 않습니다**.
- 프록시 요청에는 지역·평형·카테고리·세대수·시공사 키워드만 포함됩니다 (개인정보 미포함).
- Unix/macOS는 `chmod 600`이 자동 설정됩니다.
- 프로필 삭제: `/korea-apt-alert profile --delete` 또는 파일 직접 삭제.

## FAQ

**Q. 프록시 서버가 응답하지 않아요**
A. Render free tier는 15분 비활성 시 슬립합니다. warmup cron이 12분 간격으로 핑을 보내지만, 자정~새벽 등은 슬립 상태일 수 있습니다. 첫 호출이 30초~2분 걸릴 수 있습니다.

**Q. 가점 계산이 정확한가요?**
A. 프로필 기반 추정치입니다. 만 30세 ↔ 혼인신고일 중 늦은 해 기산, 통장 미성년 가입분 최대 5년 인정(2024.7.1. 시행, 그 이전엔 최대 2년) 등 주요 규칙은 반영되어 있지만, 부양가족 직계존속 3년 동일 세대 등록 요건은 자동 확인이 불가합니다. 정확한 가점은 [청약홈](https://www.applyhome.co.kr)에서 조회하세요.

**Q. 1주택자도 사용할 수 있나요?**
A. 네. 오피스텔, 잔여세대, 임의공급은 무주택 불문이며, "갈아타기 안내"가 자동 제공됩니다.

**Q. LH 공고의 지역이 "전국"으로 나와요**
A. LH 공고 제목에서 특정 지역을 추론할 수 없는 경우 "전국"으로 표시되며, 모든 프로필 지역 필터에서 항상 통과됩니다.

**Q. 매칭 공고가 0건이에요**
A. 프로필 지역이 좁은 경우 인접 지역(17개 매핑) 확장 제안을 받습니다. 예: 광주 → 전남·전북, 강원 → 충북.

## License

MIT
