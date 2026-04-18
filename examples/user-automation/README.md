# 사용자용 GitHub Actions 자동화 템플릿

매일 정해진 시각에 Slack으로 청약 공고 알림을 받고 싶은 일반 사용자를 위한 가이드입니다.

> **Fork 불필요.** 본인 계정에 빈 repo 하나 만들고 이 yaml 파일 1개만 올리면 됩니다.

## 3단계 셋업 (약 5분)

### 1단계 — GitHub에서 새 repo 만들기

- [github.com/new](https://github.com/new)에서 repo 생성
- 이름 예시: `my-apt-alerts` (아무거나 OK, private 권장)
- README 체크 해제, license도 선택 안 함 (빈 repo)

### 2단계 — 워크플로우 파일 복사

생성한 repo 루트에 다음 경로로 파일 하나 만들기:

```
my-apt-alerts/
└── .github/
    └── workflows/
        └── apt-notify.yml   ← 이 폴더의 apt-notify.yml 내용 복사
```

**GitHub 웹에서 하는 방법**:
1. repo 메인 페이지 → "Add file" → "Create new file"
2. 파일명 입력란에 `.github/workflows/apt-notify.yml` 입력 (슬래시까지 그대로)
3. 에디터에 [apt-notify.yml](./apt-notify.yml) 내용 전체 붙여넣기
4. 하단 "Commit new file"

### 3단계 — Secret 등록 (둘 중 하나 또는 둘 다)

repo → Settings → Secrets and variables → Actions → **New repository secret**

**(A) Slack만** 쓰려면:
- `SLACK_WEBHOOK` = `https://hooks.slack.com/services/T.../B.../xxx`

**(B) Telegram만** 쓰려면:
- `TELEGRAM_TOKEN` = `123456789:ABCdef...` (Bot Token)
- `TELEGRAM_CHAT_ID` = `-1001234567890` 또는 본인 숫자 ID

**(C) 양쪽 다** 받으려면: (A) + (B) 모두 등록 → 양쪽 채널에 동시 발송

발급 방법:
- Slack Webhook: [api.slack.com/messaging/webhooks](https://api.slack.com/messaging/webhooks)
- Telegram Bot Token: [@BotFather](https://t.me/botfather)에서 `/newbot` → 토큰 발급
- Telegram Chat ID: 본인 ID는 [@userinfobot](https://t.me/userinfobot), 그룹 ID는 그룹에 봇 초대 후 `https://api.telegram.org/bot<TOKEN>/getUpdates`에서 확인

### 4단계 — 조건 커스터마이징 (선택)

`apt-notify.yml`의 `env:` 섹션을 본인 조건으로 수정:

```yaml
env:
  REGION: "서울,경기,인천"    # 관심 지역
  DISTRICT: "강남구,서초구"   # 세부 구/군 (빈 문자열이면 전체)
  MIN_UNITS: "500"            # 500세대 이상 대단지만
  CONSTRUCTOR: "삼성,현대,GS" # 1군 건설사
  CATEGORY: "apt"             # apt만 or all
  REMINDER: "d3"              # 마감 임박 D-3 이하만
```

## 발송 시각 바꾸기

`cron` 라인 수정. GitHub Actions는 **UTC 기준**이므로 **KST 원하는 시각 - 9시간**:

| 원하는 KST | cron |
|-----------|------|
| 매일 오전 7시 (기본) | `"0 22 * * *"` |
| 매일 오전 8시 | `"0 23 * * *"` |
| 매일 오전 9시 | `"0 0 * * *"` |
| 매일 오후 7시 | `"0 10 * * *"` |
| 오전·오후 2회 (7·19시) | `"0 22,10 * * *"` |
| 주말만 오전 9시 | `"0 0 * * 0,6"` |

## 첫 실행 테스트

yaml 올리고 Secret 설정했으면:

1. repo → Actions 탭 → 왼쪽 사이드바 "청약 알림" 선택
2. 오른쪽 "Run workflow" 버튼 클릭
3. 녹색 체크 뜨면 Slack에 도착 확인

## 자주 묻는 질문

**Q. 매일 알림이 안 옴**
A. Actions 탭에서 최근 실행 로그 확인. Secret 이름이 정확히 `SLACK_WEBHOOK`인지, Webhook URL이 유효한지 체크.

**Q. 프록시 서버가 내려가면?**
A. Render free tier는 간혹 느려지지만 내려가진 않음. workflow에 `--max-time 180`이 있어 첫 호출에 1~2분 걸려도 정상 처리.

**Q. 내 조건에 안 맞는 공고가 오는 이유**
A. `env:` 섹션 필터가 충분히 좁은지 확인. `REGION`·`MIN_UNITS`·`CONSTRUCTOR` 등 강화.

**Q. GitHub Actions 무료인가?**
A. Public repo는 완전 무료, Private repo는 월 2000분(GitHub Free) 무료 → 이 workflow는 실행당 10초 내외라 하루 1회 × 30일 = 5분 수준. 충분.

## Telegram 발송 (v2.6+)

프록시가 Telegram Bot API를 직접 호출합니다. yaml은 수정 불필요 — `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` secret만 등록하면 자동으로 양쪽 채널 발송됩니다.

Bot Token 발급: [@BotFather](https://t.me/botfather) → `/newbot` → 봇 이름 설정 → Token 받기

Chat ID 확인:
- 본인 1:1 채팅: [@userinfobot](https://t.me/userinfobot)에 `/start` → ID 표시
- 그룹 채팅: 그룹에 본인 봇 초대 → `https://api.telegram.org/bot<TOKEN>/getUpdates` 호출 → `"chat":{"id":-100...}` 확인
