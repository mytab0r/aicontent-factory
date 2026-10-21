# e2e /admin: Playwright + Chromium. Base собираем сами: mcr.microsoft.com недоступен
# с раннеров ПК/VPS (TLS RST на 150.171.69/70, 20-21.10) — потому node из Docker Hub +
# браузер из CDN playwright (оба доступны). Сборка из корня репо:
#   docker build -f test/e2e/Dockerfile . && docker run --rm --ipc=host <image>
FROM node:20-bookworm-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl fonts-liberation libasound2 libatk-bridge2.0-0 \
      libatk1.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0 libnspr4 \
      libnss3 libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
      libxkbcommon0 libxrandr2 wget xdg-utils \
    && rm -rf /var/lib/apt/lists/*
RUN npm init -y >/dev/null && npm i --no-audit --no-fund playwright@1.64.1 \
    && npx playwright install chromium
COPY functions ./functions
COPY config ./config
COPY deploy/pay-page ./deploy/pay-page
COPY test/e2e/admin.e2e.mjs ./test/e2e/admin.e2e.mjs
CMD ["node", "test/e2e/admin.e2e.mjs"]
