# pay.pxbt.app/admin: подключение кошельков — spec

Карточка t_62eeb1b6. Основа: `docs/pay/research.md`.
Код: `functions/admin/index.js` (клиент `claim()`). Сервер (`/api/claim/*`, `wallet-verify.js`) по
логике не меняется; формат сообщения подписи прежний.

## DOM-контракт (на него опираются e2e)

- Кнопки: `#connect-evm`, `#connect-tron`, `#connect-solana`.
- Список адресов: `#addresses`, по строке на цепочку: `evm: 0x…`, `tron: T…`, `solana: …`.
- Журнал: `#log`, по строке на событие.
- Панель «нет кошелька»: `#nowallet` (скрыта, пока не нужна). Внутри ссылка `#nowallet a.deeplink`
  и QR `#nowallet svg`, оба указывают на deeplink этой страницы в мобильном кошельке.

## Обнаружение провайдера (порядок)

- EVM: EIP-6963 (`eip6963:requestProvider`, ждём анонсы до 300 мс, берём первый), затем `window.ethereum`.
- Tron: `window.tron` (TIP-1102, `request({method:'eth_requestAccounts'})`, затем `tron.tronWeb`),
  затем legacy `window.tronLink.request({method:'tron_requestAccounts'})` / `window.tronWeb`.
- Solana: `window.phantom.solana`, затем `window.solana` (интерфейс `connect()` + `signMessage()`).

Шаги при клике: провайдер → connect (адрес) → `POST /api/claim/nonce` → подпись → `POST /api/claim/verify`.
Nonce запрашивается только когда адрес уже получен. Каждый fetch к API идёт с тайм-аутом 15 с (AbortController).
Кнопка цепочки `disabled` на время claim, снимается в `finally`.
EVM `personal_sign` получает сообщение как `0x`-hex UTF-8 байтов (TextEncoder): в сообщении кириллица.
`#log` при выборе EIP-6963 провайдера пишет строку `evm: кошелёк <rdns>`.

## Сценарии и ожидаемый результат

Общее для всех сценариев: на странице нет `pageerror` (необработанных исключений, в том числе
`X is not defined`).

S1. Успешная привязка (отдельно для EVM, Tron, Solana).
- Дано: инжектирован кошелёк с реальным приватным ключом. EVM объявлен **только** через EIP-6963
  (без `window.ethereum`), Tron только через `window.tron` (без глобального `tronWeb` до авторизации),
  Solana через `window.phantom.solana`.
- Действие: клик по кнопке цепочки.
- Ожидается: `#log` содержит `✔ <chain>: адрес сохранён <адрес>`; `#addresses` содержит
  `<chain>: <адрес>` (EVM в нижнем регистре). Подпись настоящая (secp256k1/ed25519), сервер
  проверяет её тем же `verifyWalletSignature`, что и в проде.
- После `page.reload()` `#addresses` всё ещё содержит адрес (персистентность в KV-файле).

S2. Кошелька нет (для каждой цепочки).
- Дано: провайдеры не инжектированы.
- Ожидается: `#log` содержит `✘ <chain>: кошелёк не найден`; `#nowallet` видим; `a.deeplink` ведёт на:
  - evm: `https://link.metamask.io/dapp/<host><path>`
  - tron: `tronlinkoutside://pull.activity?param=` + urlencoded JSON с `url` этой страницы и `action:"open"`
  - solana: `https://phantom.com/ul/browse/<urlencoded url>?ref=<urlencoded origin>`
- QR (`#nowallet svg`) отрисован.
- Ни одного запроса к `/api/claim/nonce` (нет висящих/бесполезных nonce).

S3. Подпись отклонена.
- Дано: кошелёк есть, но подпись отклоняется: EVM/Solana бросают `{code:4001}`, Tron отклоняет
  промис строкой `'Confirmation declined by user'`.
- Ожидается: `#log` содержит `✘ <chain>: подпись отклонена в кошельке`; адрес не сохранён
  (`#addresses` не содержит адрес кошелька).

S3b. Подключение отклонено (отказ на шаге connect).
- Дано: кошелёк есть, connect бросает `{code:4001}` (EVM `eth_requestAccounts`, Tron `tron.request`,
  Solana `connect()`).
- Ожидается: `#log` содержит `✘ <chain>: подключение отклонено в кошельке`; ни одного запроса к
  `/api/claim/nonce`.

S4. Сеть недоступна.
- a) `/api/claim/nonce` обрывается (network error). Ожидается: `✘ <chain>: сеть недоступна`.
- b) `/api/claim/verify` не отвечает. Ожидается: через ≤15 с `✘ <chain>: сеть недоступна`, запрос
  отменён клиентом. Пока запрос висит, кнопка `disabled`; после ошибки снова кликабельна.

S5. Повторный nonce.
- Дано: успешная привязка из S1 прошла; перехвачено тело её `/api/claim/verify` (nonce + подпись).
- Ожидается: повторная отправка того же тела возвращает HTTP 400 `nonce expired or unknown`.
  Второй клик по кнопке запрашивает **новый** nonce (не равный первому) и успешно привязывает снова.

## Не в объёме

Ручной ввод адреса; Reown AppKit/WalletConnect QR-подпись (апгрейд-путь в research.md); изменения
серверной криптографии.

## CI

Job `e2e-admin` в `.github/workflows/ci.yml`: собирает образ на базе `node:20-bookworm-slim` + `playwright@1.64.1` с chromium из CDN (mcr.microsoft.com недоступен с раннеров, guard `scripts/check_e2e_base.py`, t_6de08f33)
(браузер внутри образа, раннер ничего не качает) и запускает `test/e2e/admin.e2e.mjs`. pay-image
публикуется только после зелёного `ci` (`workflow_run` success), поэтому красный e2e-admin блокирует деплой.

## Личные страницы /u/<id> (t_865ddff1)

- `<id>` — адрес получателя (EVM `0x…`, Tron `T…`, Solana base58, BTC bc1q, TON). Форма проверяется
  существующими валидаторами `functions/lib/config.js`, поэтому «несуществующий id» = адрес, не прошедший
  проверку формы → HTML 404. Отдельного реестра пользователей нет by design.
- Список сетей берётся из `NETWORKS`/`EVM_TOKENS` (`functions/pay/index.js`), а не дублируется в странице:
  для EVM-адреса — все EVM-сети с их монетами (USDT нет на Base → только USDC), для остальных — одна своя сеть.
- Выбор сети перерисовывает монеты и предупреждение «отправляйте только <монета> в сети <сеть>»; адрес и QR
  не меняются (один адрес на кошелёк).
- Лендинг `/`: кнопка «Подключить кошелёк». AppKit грузится с esm.sh только по клику; без `REOWN_PROJECT_ID`
  кнопка скрыта и показана причина, страница остаётся рабочей.

### CI

`test/test_userpage.mjs` (node, без зависимостей) — 200/404/списки сетей и монет.
`test/e2e/user.e2e.mjs` — Playwright: модалка по кнопке, смена сети → смена монет, 404, нет горизонтального
скролла на 375px. Оба гоняются job'ом `ci` (`pay.pxbt.app tests` и `e2e-admin`-образ).
