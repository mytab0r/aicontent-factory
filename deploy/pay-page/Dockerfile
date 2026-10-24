# pay.pxbt.app: Node stdlib, без npm install. Сборка из корня репо:
#   docker build -f deploy/pay-page/Dockerfile .
FROM node:22-alpine
WORKDIR /app
COPY functions ./functions
COPY config/payment-providers.json ./deploy/pay-page/payment-providers.json
COPY deploy/pay-page/server.mjs ./deploy/pay-page/server.mjs
ENV PORT=8080 DATA_DIR=/data
# projectId Reown публичный (уходит в HTML каждому браузеру), не секрет; secrets.json перекрывает
ENV REOWN_PROJECT_ID=987afabd28d84f735c75cab6a6742e54
RUN mkdir /data && chown node:node /data
USER node
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
CMD ["node", "deploy/pay-page/server.mjs"]
