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
  включённые пары. `PAIRS` — известные пары монета+сеть.
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

## Доступ к /admin

Cloudflare Zero Trust → Access → приложение на `pay.pxbt.app/admin` (и
`/api/admin/*` + `/api/claim/*`): policy = email владельца. Подпись кошелька —
второй фактор (адрес не сохранится без валидной подписи).

## Деплой (однократно, из CF dashboard, без wrangler-секрета на сервере)

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
