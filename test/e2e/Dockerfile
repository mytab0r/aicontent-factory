# e2e /admin: Playwright + Chromium из официального образа. Сборка из корня репо:
#   docker build -f test/e2e/Dockerfile . && docker run --rm --ipc=host <image>
FROM mcr.microsoft.com/playwright:v1.64.1-noble
WORKDIR /app
RUN npm init -y >/dev/null && npm i --no-audit --no-fund playwright@1.64.1
COPY functions ./functions
COPY config ./config
COPY deploy/pay-page ./deploy/pay-page
COPY test/e2e/admin.e2e.mjs ./test/e2e/admin.e2e.mjs
CMD ["node", "test/e2e/admin.e2e.mjs"]
