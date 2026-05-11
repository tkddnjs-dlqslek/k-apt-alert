# Python 3.12 + Node.js 20 통합 base 이미지 (community, 100M+ pulls)
# 이전: python:3.12-slim + NodeSource 수동 설치 → Render free tier 빌드 OOM/timeout
FROM nikolaik/python-nodejs:python3.12-nodejs20-slim

# kordoc CLI 글로벌 설치 — HWP·HWPX·PDF·XLSX·DOCX → Markdown
RUN npm install -g --omit=dev kordoc && npm cache clean --force

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
