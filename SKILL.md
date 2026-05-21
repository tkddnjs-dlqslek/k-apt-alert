# SKILL.md — 본문이 이동했습니다

이 스킬의 정식 본문은 Claude Code **플러그인 구조**에 맞춰 다음 경로로 이동했습니다 (단일 소스 유지):

### → [`skills/korea-apt-alert/SKILL.md`](skills/korea-apt-alert/SKILL.md)

이 파일은 리다이렉트 안내일 뿐 스킬 지시문이 아닙니다 (그래서 frontmatter가 없습니다 — 이중 등록 방지).

## 설치

### 플러그인으로 (권장)
```
/plugin marketplace add tkddnjs-dlqslek/k-apt-alert
/plugin install k-apt-alert@k-apt-alert-marketplace
```
스킬 + 자격 판별 에이전트 + MCP 서버가 한 번에 설치됩니다.

### 스킬만 수동 설치
```bash
# Claude Code (macOS/Linux/WSL)
git clone https://github.com/tkddnjs-dlqslek/k-apt-alert.git /tmp/k-apt-alert \
  && cp -r /tmp/k-apt-alert/skills/korea-apt-alert ~/.claude/skills/korea-apt-alert
```
```powershell
# Claude Code (Windows PowerShell)
git clone https://github.com/tkddnjs-dlqslek/k-apt-alert.git $env:TEMP\k-apt-alert
Copy-Item -Recurse -Force "$env:TEMP\k-apt-alert\skills\korea-apt-alert" "$env:USERPROFILE\.claude\skills\korea-apt-alert"
```

자세한 사용법·기능은 [README.md](README.md) 참고.
