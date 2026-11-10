# tarot-funnel — Node.js stdlib only, no npm deps
FROM node:22-alpine AS base
WORKDIR /app
COPY server.js index.html ./
RUN adduser -D -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
ENV PORT=8081
EXPOSE 8081
CMD ["node", "server.js"]
