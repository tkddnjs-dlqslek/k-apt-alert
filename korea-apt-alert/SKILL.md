---
name: korea-apt-alert
description: 한국 청약 공고를 조회·분석하고 Slack/Telegram으로 알림을 보낸다. 공공데이터포털 6개 API를 프록시 경유로 통합 조회하며, 사용자 API 키 없이 동작한다.
license: MIT
metadata:
  category: real-estate
  locale: ko-KR
  phase: v1
---

# 한국 청약 공고 알리미

공공데이터포털의 청약홈 분양정보 API를 프록시 경유로 조회하여 최신 청약 공고를 분석·알림한다.

## 사용 예시

- "최신 청약 공고 알려줘"
- "서울 아파트 청약 조회해줘"
- "경기도 30평대 청약 있어?"
- "이번 달 LH 공공분양 뭐 나왔어?"
- "청약 공고 조회해서 Slack으로 보내줘"

## 사전 조건

### 필수

없음. 프록시 서버가 공공데이터포털 API 키를 관리하므로 사용자는 별도 키가 불필요하다.

### 선택 (알림 기능)

Slack 또는 Telegram으로 알림을 받으려면 아래 환경변수를 `~/.config/k-skill/secrets.env`에 설정한다.

```
# Slack — Incoming Webhook URL (하나 이상)
KSKILL_APT_SLACK_WEBHOOK=https://hooks.slack.com/services/T.../B.../xxx

# Telegram — Bot Token + Chat ID
KSKILL_APT_TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
KSKILL_APT_TELEGRAM_CHAT_ID=-1001234567890
```

**Slack Webhook 발급**: Slack 워크스페이스 → 앱 관리 → Incoming Webhooks → 채널 선택 → URL 복사
**Telegram Bot 발급**: @BotFather에게 `/newbot` → 토큰 발급 → 채널에 봇 추가 → Chat ID 확인

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

### 1단계: 청약 공고 조회

프록시 서버에서 공고를 가져온다.

```bash
# 전체 조회
curl -s "https://k-apt-alert-proxy.onrender.com/v1/apt/announcements?category=all&active_only=true"

# 특정 카테고리만
curl -s "https://k-apt-alert-proxy.onrender.com/v1/apt/announcements?category=apt&active_only=true"

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

### 2단계: 분석 및 분류

조회된 공고를 아래 기준으로 분석한다. 분류는 네가(에이전트가) 직접 수행한다.

**분류 필드:**
- `region`: 지역 (서울, 경기, 인천, 부산 등)
- `district`: 세부 지역 (강남구, 분당구 등 — 주소에서 추출)
- `type`: 민영 / 공공 / 재건축 / 재개발
- `size`: 소형(<60m²) / 중형(60~85m²) / 대형(>85m²)
- `priority`: HIGH / MEDIUM / LOW

**우선순위 판정 기준:**
- **HIGH**: 1군 건설사(삼성, 현대, GS, 대우, 롯데, 포스코, DL, HDC) + 수도권 + 500세대 이상
- **HIGH**: LH 뉴홈/공공분양 + 수도권
- **MEDIUM**: 수도권 or 대형 건설사 중 하나
- **LOW**: 그 외

### 3단계: 결과 출력

사용자가 원하는 형식으로 결과를 정리한다.

**기본 출력 (터미널):**
조회된 공고를 마크다운 테이블로 정리하여 보여준다.

| 이름 | 지역 | 접수기간 | 세대수 | 평형 | 우선순위 |
|------|------|----------|--------|------|----------|

**조건 필터링:**
사용자가 지역, 평형, 카테고리 등을 지정하면 해당 조건으로 필터링한다.

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
      {"type": "section", "text": {"type": "mrkdwn", "text": "*📅 접수기간:* 20260415 ~ 20260420\n*🏢 타입:* 민영 / 중형/대형\n*🔴 우선순위:* HIGH\n*💬 분석:* _1군 건설사 + 서초구 입지 + 641세대_"}},
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
    "text": "🏠 <b>래미안 원펜타스</b> — 서울 서초구\n\n📅 <b>접수기간:</b> 20260415 ~ 20260420\n🏢 <b>타입:</b> 민영 / 중형/대형\n🔴 <b>우선순위:</b> HIGH\n💬 <i>1군 건설사 + 서초구 입지</i>\n\n<a href=\"https://www.applyhome.co.kr\">청약홈 바로가기 →</a>",
    "parse_mode": "HTML",
    "disable_web_page_preview": true
  }'
```

HIGH 우선순위는 알림음 ON (`"disable_notification": false`), 나머지는 무음 발송.

## 성공 기준

- 프록시에서 공고 JSON을 정상 수신
- 사용자 조건에 맞게 필터링 및 분류 완료
- 결과를 마크다운 테이블로 출력
- (선택) Slack/Telegram 알림 발송 성공

## 실패 시나리오

| 상황 | 대응 |
|------|------|
| 프록시 응답 없음 | "프록시 서버가 응답하지 않습니다. 잠시 후 다시 시도해주세요." |
| 공고 0건 | "현재 접수 중인 청약 공고가 없습니다." |
| Slack webhook 미설정 | "Slack webhook이 설정되지 않았습니다. ~/.config/k-skill/secrets.env에 KSKILL_APT_SLACK_WEBHOOK을 추가해주세요." |
| Telegram 미설정 | "Telegram 설정이 없습니다. KSKILL_APT_TELEGRAM_TOKEN과 KSKILL_APT_TELEGRAM_CHAT_ID를 설정해주세요." |

## 기술 노트

- 프록시 서버: `https://k-apt-alert-proxy.onrender.com` (Render free tier — 15분 비활성 시 슬립)
- 데이터 출처: 공공데이터포털 한국부동산원_청약홈 분양정보 조회 서비스
- API 키: 프록시 서버에서 관리 — 사용자 노출 없음
- 프록시 소스코드: https://github.com/tkddnjs-dlqslek/k-apt-alert
