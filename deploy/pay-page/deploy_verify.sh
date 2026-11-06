#!/usr/bin/env bash
# t_1b6fdb47: ждём, пока https://pay.pxbt.app/healthz отдаст sha собранного образа (Watchtower подтянул :latest).
# Не дождались за TIMEOUT -> TG-алерт и exit 1. Алерт не доставлен -> exit 2 (громко, без `|| true`).
# Env: WANT_SHA (обяз.), URL, TIMEOUT, INTERVAL, TG_API, TG_BOT_TOKEN, TG_CHAT_ID, TG_THREAD_ID.
# Обе ветки проверяет pipeline/test_pay_deploy_verify.py на локальном фейк-сервере.
set -u
: "${WANT_SHA:?WANT_SHA пуст}"
URL="${URL:-https://pay.pxbt.app/healthz}"
TIMEOUT="${TIMEOUT:-900}"
INTERVAL="${INTERVAL:-30}"
TG_API="${TG_API:-https://api.telegram.org}"
START=$(date +%s)
echo "Ждём деплой: $URL должен вернуть sha=$WANT_SHA (таймаут ${TIMEOUT}с)"
while :; do
  ELAPSED=$(( $(date +%s) - START ))
  GOT=$(curl -sf --max-time 10 "$URL" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("sha",""))' 2>/dev/null)
  if [ "$GOT" = "$WANT_SHA" ]; then echo "OK: healthz sha=$GOT (${ELAPSED}с)"; exit 0; fi
  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then break; fi
  echo "sha=${GOT:-empty}, ждём $WANT_SHA (${ELAPSED}с / ${TIMEOUT}с)"
  sleep "$INTERVAL"
done
echo "::error::таймаут ${TIMEOUT}с: healthz sha=${GOT:-empty}, ожидали $WANT_SHA"
if [ -z "${TG_BOT_TOKEN:-}" ] || [ -z "${TG_CHAT_ID:-}" ]; then echo "::error::TG секреты пусты, алерт не отправлен"; exit 2; fi
TEXT="pay.pxbt.app: деплой не доехал за $((TIMEOUT / 60)) мин. Ожидали версию ${WANT_SHA:0:7}, прод отдаёт ${GOT:-нет ответа}. $URL"
RESP=$(curl -sS -m 20 "$TG_API/bot$TG_BOT_TOKEN/sendMessage" -d chat_id="$TG_CHAT_ID" \
  ${TG_THREAD_ID:+-d message_thread_id="$TG_THREAD_ID"} --data-urlencode text="$TEXT")
if printf '%s' "$RESP" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") is True else 1)' 2>/dev/null
then echo "TG-алерт отправлен"; else echo "::error::TG-алерт не доставлен: $RESP"; exit 2; fi
exit 1
