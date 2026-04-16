---
name: korea-apt-alert
description: 한국 청약 공고를 개인 프로필 기반으로 조회·분석하고 Slack/Telegram으로 알림을 보낸다. 공공데이터포털 6개 API를 프록시 경유로 통합 조회하며, 사용자 API 키 없이 동작한다.
license: MIT
metadata:
  category: real-estate
  locale: ko-KR
  phase: v1
---

# 한국 청약 공고 알리미

공공데이터포털의 청약홈 분양정보 API를 프록시 경유로 조회하여 **사용자 프로필 기반**으로 최신 청약 공고를 필터링·분석·알림한다.

## 사용 예시

- "최신 청약 공고 알려줘"
- "서울 아파트 청약 조회해줘"
- "내 프로필 설정해줘" / `/korea-apt-alert setup`
- "내 조건에 맞는 청약 있어?"
- "청약 공고 조회해서 Slack으로 보내줘"

---

## 개인화 프로필 시스템

### 프로필 저장 위치

`~/.config/k-skill/apt-alert-profile.json`

### 프로필 설정 (`setup`)

사용자가 "프로필 설정", "setup", "내 정보 등록" 등을 요청하면 아래 항목을 **대화형으로** 하나씩 물어본다. 사용자가 모르거나 건너뛰고 싶은 항목은 null로 저장한다.

#### 질문 순서 및 선택지

**1. 출생연도**
- 자유 입력 (예: 1995)
- 만 나이를 자동 계산하여 `age` 필드에 저장

**2. 선호 지역 (복수 선택)**
- [ ] 서울
- [ ] 경기
- [ ] 인천
- [ ] 부산
- [ ] 대구
- [ ] 광주
- [ ] 대전
- [ ] 울산
- [ ] 세종
- [ ] 강원
- [ ] 충북
- [ ] 충남
- [ ] 전북
- [ ] 전남
- [ ] 경북
- [ ] 경남
- [ ] 제주
- [ ] 전체 (모든 지역)

**3. 가구 구성**
- (a) 1인 가구 (미혼)
- (b) 신혼부부 (혼인 7년 이내)
- (c) 기혼 (자녀 없음)
- (d) 기혼 + 자녀 있음 → 자녀 수 추가 질문
- (e) 한부모 가정

**4. 무주택 여부**
- (a) 무주택 — 본인 명의 주택 없음
- (b) 유주택 — 본인 또는 세대원 명의 주택 보유

**5. 청약통장**
- (a) 없음
- (b) 있음 → 가입기간(년), 납입횟수(회) 추가 질문

**6. 연소득 구간**
- (a) 3천만원 이하
- (b) 3천~5천만원
- (c) 5천~7천만원
- (d) 7천~1억원
- (e) 1억원 초과
- (f) 모름 / 건너뛰기

**7. 선호 평형**
- (a) 소형 (전용 60m² 미만 / ~18평)
- (b) 중형 (60~85m² / 18~25평)
- (c) 대형 (85m² 초과 / 25평+)
- (d) 상관없음

### 프로필 JSON 스키마

```json
{
  "birth_year": 1995,
  "age": 31,
  "regions": ["서울", "경기", "인천"],
  "household": {
    "type": "newlywed",
    "children_count": 0
  },
  "homeless": true,
  "subscription_account": {
    "has_account": true,
    "years": 5,
    "deposit_count": 60
  },
  "annual_income": "5천~7천만원",
  "income_bracket": "mid",
  "preferred_size": ["소형", "중형"],
  "updated_at": "2026-04-16"
}
```

`household.type` 값: `"single"` | `"newlywed"` | `"married_no_child"` | `"married_with_child"` | `"single_parent"`
`income_bracket` 값: `"low"` (≤3천) | `"mid_low"` (3천~5천) | `"mid"` (5천~7천) | `"mid_high"` (7천~1억) | `"high"` (>1억) | `null`

### 프로필 저장

설정 완료 후 `~/.config/k-skill/apt-alert-profile.json`에 JSON으로 저장한다.

---

## 청약 유형별 자격 매칭 로직

프로필이 있으면 아래 로직으로 **추천 유형**을 자동 판정하여 해당 카테고리만 우선 조회한다.

### 매칭 테이블

| 카테고리 | 청약통장 | 무주택 | 소득 기준 | 추천 대상 |
|----------|---------|--------|-----------|-----------|
| **APT 일반분양** | 필수 (가입 2년+, 지역별 상이) | 필수 | 없음 | 통장 보유 + 무주택 |
| **오피스텔/도시형** | 불필요 | 불필요 | 없음 | **누구나** (만 19세+) |
| **LH 공공분양** | 필수 (가입 6개월+) | 필수 | 도시근로자 월평균 100~130% | 통장 보유 + 무주택 + 소득 mid_low~mid |
| **APT 잔여세대** | 불필요 | 불필요 | 없음 | **누구나** |
| **공공지원민간임대** | 불필요 | 필수 | 도시근로자 월평균 120% | 무주택 + 소득 low~mid |
| **임의공급** | 불필요 | 불필요 | 없음 | **누구나** (선착순) |

### 특별공급 자격 판정

프로필 기반으로 해당하는 특별공급 유형을 안내한다.

| 특별공급 | 조건 |
|----------|------|
| **신혼부부** | household.type = "newlywed", 무주택, 소득 기준 충족 |
| **생애최초** | 무주택, 5년 이상 소득세 납부, 소득 기준 충족 |
| **다자녀** | children_count >= 2, 무주택 |
| **노부모 부양** | age >= 만 25세 + 만 65세 이상 직계존속 3년 부양 (프로필에서 확인 불가 → 안내만) |
| **기관 추천** | 국가유공자, 장애인 등 (프로필에서 확인 불가 → 안내만) |

### 추천 로직 (에이전트가 실행)

```
1. 프로필 로드 (~/.config/k-skill/apt-alert-profile.json)
2. 프로필이 없으면 → "프로필을 설정하면 맞춤 추천이 가능합니다. 설정하시겠어요?" 안내
3. 프로필이 있으면:
   a. 매칭 테이블로 추천 카테고리 결정
   b. 선호 지역으로 필터링
   c. 선호 평형으로 필터링
   d. 특별공급 자격 해당 시 안내 메시지 추가
   e. 우선순위에 개인 가점 반영 (통장 기간 길수록, 무주택이면 UP)
```

---

## 사전 조건

### 필수

없음. 프록시 서버가 공공데이터포털 API 키를 관리하므로 사용자는 별도 키가 불필요하다.

### 선택 (알림 기능)

Slack 또는 Telegram으로 알림을 받으려면 아래 환경변수를 `~/.config/k-skill/secrets.env`에 설정한다.

```
# Slack — Incoming Webhook URL
KSKILL_APT_SLACK_WEBHOOK=https://hooks.slack.com/services/T.../B.../xxx

# Telegram — Bot Token + Chat ID
KSKILL_APT_TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
KSKILL_APT_TELEGRAM_CHAT_ID=-1001234567890
```

## 조회 가능한 카테고리

| ID | 이름 | 설명 |
|---|---|---|
| `apt` | APT 일반분양 | 아파트 일반분양 (월 25일 배치 업데이트) |
| `officetell` | 오피스텔/도시형 | 오피스텔, 도시형생활주택, 민간임대 (실시간) |
| `lh` | LH 공공분양 | 뉴홈, 행복주택 등 공공주택 (실시간) |
| `remndr` | APT 잔여세대 | 미계약/미분양 재공급 — 청약통장 불필요 |
| `pbl_pvt_rent` | 공공지원민간임대 | 시세 대비 저렴, 최대 10년 거주 |
| `opt` | 임의공급 | 사업주체 자율 공급 — 선착순 계약 |

## 워크플로우

### 0단계: 프로필 확인

```
1. ~/.config/k-skill/apt-alert-profile.json 파일 존재 확인
2. 있으면 → 로드하여 필터링에 활용
3. 없으면 → 프로필 없이 전체 조회 (프로필 설정 안내 포함)
```

### 1단계: 청약 공고 조회

프록시 서버에서 공고를 가져온다. 프로필이 있으면 추천 카테고리와 지역으로 필터링한다.

```bash
# 전체 조회
curl -s "https://k-apt-alert-proxy.onrender.com/v1/apt/announcements?category=all&active_only=true"

# 특정 카테고리
curl -s "https://k-apt-alert-proxy.onrender.com/v1/apt/announcements?category=apt&active_only=true"

# 지역 필터 (복수 가능, 쉼표 구분)
curl -s "https://k-apt-alert-proxy.onrender.com/v1/apt/announcements?region=서울,경기,인천"

# 조회 기간 조정 (기본 2개월)
curl -s "https://k-apt-alert-proxy.onrender.com/v1/apt/announcements?months_back=3"
```

응답 형식:
```json
{
  "count": 15,
  "announcements": [
    {
      "id": "2026000123",
      "name": "래미안 원펜타스",
      "region": "서울",
      "address": "서울특별시 서초구 ...",
      "period": "20260415 ~ 20260420",
      "rcept_end": "20260420",
      "total_units": "641",
      "house_type": "민영",
      "constructor": "삼성물산(주)",
      "url": "https://www.applyhome.co.kr/...",
      "speculative_zone": "Y",
      "price_controlled": "N",
      "house_category": "APT",
      "size": "중형/대형"
    }
  ]
}
```

### 2단계: 프로필 기반 분석

조회된 공고를 프로필 기준으로 분석한다. 분류는 에이전트가 직접 수행한다.

**분류 필드:**
- `region`: 지역 (서울, 경기, 인천, 부산 등)
- `district`: 세부 지역 (강남구, 분당구 등 — 주소에서 추출)
- `type`: 민영 / 공공 / 재건축 / 재개발
- `size`: 소형(<60m²) / 중형(60~85m²) / 대형(>85m²)
- `priority`: HIGH / MEDIUM / LOW
- `eligibility`: 자격 해당 여부 (프로필 기반)
- `special_supply`: 해당하는 특별공급 유형

**우선순위 판정 기준 (프로필 반영):**
- **HIGH**: 선호 지역 + 선호 평형 + 자격 충족 + 1군 건설사 or 공공분양
- **MEDIUM**: 위 조건 중 2개 이상 충족
- **LOW**: 그 외

### 3단계: 결과 출력

**기본 출력 (마크다운 테이블):**

| 이름 | 지역 | 접수기간 | 세대수 | 평형 | 우선순위 | 자격 |
|------|------|----------|--------|------|----------|------|

프로필이 있으면 결과 상단에 아래 요약을 포함한다:

```
📋 프로필 요약: 만 31세 / 서울·경기·인천 / 신혼부부 / 무주택 / 통장 5년
🏷️ 추천 유형: APT 일반분양, LH 공공분양, 오피스텔
⭐ 특별공급: 신혼부부 특별공급 자격 해당
```

### 4단계: 알림 발송 (선택)

사용자가 `--notify`, "알림 보내줘", "Slack으로 보내줘" 등을 요청한 경우에만 실행한다.

**Slack 발송:**
```bash
curl -X POST "$KSKILL_APT_SLACK_WEBHOOK" \
  -H "Content-Type: application/json" \
  -d '{
    "blocks": [
      {"type": "header", "text": {"type": "plain_text", "text": "🏠 래미안 원펜타스 — 서울 서초구"}},
      {"type": "divider"},
      {"type": "section", "text": {"type": "mrkdwn", "text": "*📅 접수기간:* 20260415 ~ 20260420\n*🏢 타입:* 민영 / 중형/대형\n*🔴 우선순위:* HIGH\n*⭐ 특별공급:* 신혼부부 자격 해당\n*💬 분석:* _1군 건설사 + 서초구 입지 + 641세대_"}},
      {"type": "divider"},
      {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "청약홈 바로가기 →"}, "url": "https://www.applyhome.co.kr", "style": "primary"}]}
    ]
  }'
```

**Telegram 발송:**
```bash
curl -X POST "https://api.telegram.org/bot${KSKILL_APT_TELEGRAM_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "'"$KSKILL_APT_TELEGRAM_CHAT_ID"'",
    "text": "🏠 <b>래미안 원펜타스</b> — 서울 서초구\n\n📅 <b>접수기간:</b> 20260415 ~ 20260420\n🏢 <b>타입:</b> 민영 / 중형/대형\n🔴 <b>우선순위:</b> HIGH\n⭐ <b>특별공급:</b> 신혼부부 자격 해당\n💬 <i>1군 건설사 + 서초구 입지</i>\n\n<a href=\"https://www.applyhome.co.kr\">청약홈 바로가기 →</a>",
    "parse_mode": "HTML",
    "disable_web_page_preview": true
  }'
```

HIGH 우선순위는 알림음 ON, 나머지는 무음 발송.

## 성공 기준

- 프록시에서 공고 JSON을 정상 수신
- 프로필이 있으면 프로필 기반 필터링 + 자격 판정 + 특별공급 안내
- 프로필이 없으면 전체 조회 + 프로필 설정 안내
- 결과를 마크다운 테이블로 출력
- (선택) Slack/Telegram 알림 발송 성공

## 실패 시나리오

| 상황 | 대응 |
|------|------|
| 프록시 응답 없음 | "프록시 서버가 응답하지 않습니다. 잠시 후 다시 시도해주세요." |
| 공고 0건 | "현재 접수 중인 청약 공고가 없습니다." |
| 프로필 없음 | 전체 조회 후 "프로필을 설정하면 맞춤 추천이 가능합니다" 안내 |
| 프로필 매칭 0건 | "현재 조건에 맞는 공고가 없습니다. 지역이나 평형 조건을 넓혀보세요." |
| Slack/Telegram 미설정 | 해당 환경변수 설정 안내 |

## 기술 노트

- 프록시 서버: `https://k-apt-alert-proxy.onrender.com` (Render free tier — 15분 비활성 시 슬립)
- 프로필: `~/.config/k-skill/apt-alert-profile.json` (로컬 저장, 서버 전송 없음)
- 데이터 출처: 공공데이터포털 한국부동산원_청약홈 분양정보 조회 서비스
- API 키: 프록시 서버에서 관리 — 사용자 노출 없음
- 프록시 소스코드: https://github.com/tkddnjs-dlqslek/k-apt-alert
