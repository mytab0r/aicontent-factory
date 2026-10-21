# pay.pxbt.app — страница оплаты криптой (CF Pages + Functions + KV, $0)

Одна ссылка на оплату: клиент открывает `/i/<invoice>`, выбирает пару
монета+сеть из включённых, видит адрес, QR и предупреждение «только эта сеть».
Адреса получателя НЕ вводятся вручную: владелец один раз подключает кошелёк
в `/admin` и подписывает сообщение — подпись доказывает владение адресом.
Факт оплаты проверяется по блокчейну (Tronscan / публичные EVM-RPC), без
посредников и без хранения чьих-либо средств. Seed и приватные ключи
не запрашиваются нигде и никогда.

## Структура

- `functions/lib/wallet-verify.js` — проверка подписей: EVM personal_sign
  (восстановление адреса, keccak/EIP-191), Tron signMessageV2 (префикс
  `\x19TRON Signed Message:`), Solana ed25519. Криптография — vendored
  `@noble/{secp256k1,ed25519,hashes}` (MIT, `functions/vendor/`), никаких
  внешних npm-зависимостей.
- `functions/lib/config.js` — конфиг в KV (`config`): публичные адреса +
  включённые пары. `PAIRS` — известные пары монета+сеть с контрактом и decimals
  (сверены `decimals()` on-chain): USDT на Tron/Ethereum/Polygon/Arbitrum (6), USDT BSC (18),
  USDC на Base (6; нативного USDT в Base нет).
- `functions/lib/paycheck.js` — проверка оплаты: Tronscan
  `token_trc20/transfers` (аналог autopilot/crypto.py), для EVM —
  `eth_getLogs` Transfer(to=адрес) на публичных RPC publicnode.com;
  сравнение суммы в минорных юнитах (USDT = 6 dec).
- `functions/api/claim/nonce.js` — одноразовый nonce (KV, TTL 300s).
- `functions/api/claim/verify.js` — проверка подписи + сохранение адреса.
  Nonce сжигается только при успехе.
- `functions/api/admin/config.js` — чтение/правка галочек пар.
- `functions/api/invoice/create.js` — создать инвойс (POST {amount}).
- `functions/api/invoice/[[id]].js` — GET инвойс / POST выбор пары /
  PUT проверка оплаты.
- `functions/i/[[id]].js` — страница клиента.
- `functions/admin/index.js` — админка (подключение кошельков + галочки).
- `test/` — тесты (node, без зависимостей): векторы подписей для трёх
  цепочек (генерировались ethers/tronweb/tweetnacl), негативные кейсы,
  KV-заглушка.

## Провайдеры (расширяемо данными)

`config/payment-providers.json` — список провайдеров и их полей (`text` / `secret` /
`select`, опционально `check`). Новый провайдер = новая запись, UI админки не правится.
Сейчас: `crypto` (кошельки через подпись) и `paypal` (Client ID, Secret, live/sandbox,
кнопка «Проверить» = OAuth `client_credentials` к api-m.paypal.com / sandbox).
Секреты пишутся только в `$DATA_DIR/secrets.json` (chmod 600, вне git), наружу —
маска; пустое поле при сохранении = оставить прежнее значение.

## Деплой: контейнер, ghcr + Watchtower (основной путь)

`deploy/pay-page/server.mjs` — Node stdlib, те же обработчики из `functions/`,
KV = `$DATA_DIR/kv.json`. CI: `ci` (тесты + smoke образа) → на master
`pay-image` пушит `ghcr.io/mytab0r/pay-pxbt:latest` → Watchtower на VPS обновляет.

Однократно на VPS (рядом с `docker-compose.yml` из этой папки):
1. `.env`: `OWNER_EMAIL`, `CF_ACCESS_TEAM_DOMAIN` (`<team>.cloudflareaccess.com`),
   `CF_ACCESS_AUD` (AUD-тег приложения Access), `PAY_API_TOKEN` (для создания счетов ботом).
2. `mkdir -p data && sudo chown 1000:1000 data` (процесс в контейнере — uid 1000 `node`;
   root-owned каталог = контейнер не стартует с ошибкой про chown), затем `docker compose up -d`; Cloudflare Tunnel/прокси: `pay.pxbt.app` → `127.0.0.1:8090`.
3. Zero Trust → Access → приложение `pay.pxbt.app/admin`, `/api/admin/*`, `/api/claim/*`,
   policy = email владельца. Сервер сам проверяет JWT Access (RS256, aud, iss, exp, email);
   без настроенных `CF_ACCESS_*` админка закрыта (403).

Реестр адресов для агентов: `curl 'https://pay.pxbt.app/api/address?chain=evm|tron|solana'`
-> `{ chain, address }`; адреса нет — HTTP 404 с явной ошибкой (агент обязан упасть, не брать
дефолт). Единственный источник — тот же KV `config`, что наполняется подписанным claim в `/admin`.

Создать счёт: `curl -X POST https://pay.pxbt.app/api/invoice -H "authorization: Bearer $PAY_API_TOKEN" -d '{"amount":1}'`.

Сопоставление оплаты: адрес у всех счетов общий, поэтому сумма счёта уникальна —
к сумме (в центах) добавляется случайный хвост 1..999 микроюнитов (`1.000437`), клиент
видит и платит ровно её, проверка — точное совпадение в 6-знаковых микроюнитах.
Каждый засчитанный tx пишется в KV `paidtx:<chain>:<tx>` = id счёта: один перевод закрывает
только один счёт. Недоплата/переплата/перевод без хвоста счёт не закрывают — разбор вручную.
Ponytail: хвостов 999 на одну базовую сумму; коллизия возможна при сотнях одновременно
открытых счетов на одну сумму — тогда перейти на уникальный адрес на счёт.

## Доступ к /admin

Cloudflare Zero Trust → Access → приложение на `pay.pxbt.app/admin` (и
`/api/admin/*` + `/api/claim/*`): policy = email владельца. Подпись кошелька —
второй фактор (адрес не сохранится без валидной подписи).

## Альтернатива: CF Pages (без контейнера)

1. dash.cloudflare.com → Workers & Pages → Create → Pages → Connect to Git →
   репозиторий `mytab0r/aicontent-factory`, ветка с этой папкой как root
   (или задать Root directory). Build command: пусто, Output: `/`.
2. Pages project → Settings → Functions → KV namespace bindings:
   `KV` → создать namespace `pay_pxbt_kv` (Free-плана достаточно).
3. Custom domain: `pay.pxbt.app` (зона pxbt.app уже в CF).
4. Zero Trust → Access (см. выше).
5. Подключить кошельки: открыть `https://pay.pxbt.app/admin`, подключить
   EVM/Tron(/Solana), включить пары, «Сохранить».
6. Создать тестовый инвойс и проверить оплату (acceptance #4):
   `curl -X POST https://pay.pxbt.app/api/invoice -H 'content-type: application/json' -d '{"amount":1}'`
   → открыть URL, выбрать USDT TRC20, перевести 1 USDT на показанный адрес,
   нажать «Проверить» → статус `paid`.

## Тесты

`node test/test_wallet_verify.mjs && node test/test_api.mjs` — или CI.
Live-проверка Tronscan/RPC уже выполнена при разработке (см. комментарий
задачи); `checkPayment` покрыт форматами ответов реальных API.
