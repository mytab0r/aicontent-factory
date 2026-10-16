# pay.pxbt.app/admin: подключение EVM / Tron / Solana кошельков — research

Дата: 2026-10-16. Карточка: t_62eeb1b6.

## Что сломано сейчас (факт, а не гипотеза)

`functions/admin/index.js` → `claim(chain)`:

1. EVM: обращение к голому идентификатору `ethereum.request(...)`. Если расширения нет,
   `window.ethereum` не определён и бросается `ReferenceError: ethereum is not defined`
   (именно это видит владелец). EIP-6963 discovery не используется, поэтому при нескольких
   расширениях выбирается случайное, а кошельки, которые не пишут `window.ethereum`, не видны.
2. Tron / Solana: сначала `POST /api/claim/nonce`, и только потом проверка наличия
   кошелька. Без кошелька nonce создаётся в KV зря, а владелец видит сырое
   «TronLink не подключён» / «Phantom не найден» без пути, что делать дальше.
3. Tron: используется `window.tronWeb.ready`. Это legacy API. TronLink с 2025 года
   инжектит `window.tron` (TIP-1102 `eth_requestAccounts`), а `tronWeb` до авторизации
   равен `false`. Если не запросить доступ, `ready` никогда не станет true.
4. Solana: проверка `solana.isPhantom` отсекает остальные кошельки (Solflare, Backpack),
   хотя у них тот же `connect()/signMessage()`.
5. Ошибки отклонения подписи и сети показываются сырыми строками; у fetch нет тайм-аута.

Сервер (`functions/api/claim/*`, `functions/lib/wallet-verify.js`) работает:
`test/test_wallet_verify.mjs` на векторах ethers/tronweb/tweetnacl зелёный. Править нужно клиент.

## Ограничения среды

- Владелец работает из обычного браузера, расширения может не быть. Основной кошелёк
  у него на телефоне.
- Репо и контейнер pay-pxbt: Node stdlib, **без npm-зависимостей и без бандлера**
  (`deploy/pay-page/Dockerfile`, README). Криптография vendored (`functions/vendor/noble`).
- /admin закрыт Zoraxy SSO (логин/пароль) и CF Access. Мобильный in-app браузер кошелька
  проходит тот же SSO-логин: это обычный браузер.
- Ручной ввод адреса без подписи не рассматривается: подпись доказывает владение.

## Варианты

| Вариант | Что даёт | Цена / зависимость | Вердикт |
|---|---|---|---|
| **EIP-6963 discovery** + fallback `window.ethereum` | Корректный выбор среди нескольких расширений, нет ReferenceError | 0, ~20 строк, стандарт | **Берём** |
| **Reown AppKit / WalletConnect v2** (QR с телефона) | Подпись с телефона без расширения, 600+ кошельков | Бесплатный projectId на cloud.reown.com (регистрация внешнего аккаунта), npm `@reown/appkit` 1.8.x + бандлер или CDN-ESM с десятками модулей, relay-сервер Reown в критическом пути. Tron в AppKit не поддерживается штатно | Отложено (см. ниже) |
| **TronLink: `window.tron` (TIP-1102) / tronwallet-adapter** | Современный connect, коды 4001 | Адаптер = npm + бандлер; сам `window.tron` бесплатный | **Берём `window.tron` напрямую**, legacy `tronLink`/`tronWeb` как fallback |
| **Solana Wallet Adapter / Wallet Standard** | Все Solana-кошельки | npm + React/бандлер | Не берём. Используем общий интерфейс `window.phantom.solana` / `window.solana` (`connect`, `signMessage`), который реализуют Phantom, Solflare и Backpack |
| **Deeplink «открыть эту страницу в in-app браузере кошелька»** + QR | Путь без расширения: сканируешь QR телефоном, страница открывается внутри кошелька, где провайдер инжектирован, и подписываешь там | 0, без регистрации. QR рисует vendored `qrcode-generator` (MIT, 1 файл) | **Берём как путь «нет расширения»** |

Deeplink-форматы (официальные доки):
- MetaMask: `https://link.metamask.io/dapp/{host/path}` открывает dapp во встроенном браузере.
  https://docs.metamask.io/metamask-connect/evm/guides/metamask-exclusive/use-deeplinks/
- Phantom: `https://phantom.com/ul/browse/<url-encoded url>?ref=<url-encoded origin>`.
  https://docs.phantom.com/phantom-deeplinks/other-methods/browse
- TronLink: `tronlinkoutside://pull.activity?param=<urlencoded {"url":..,"action":"open","protocol":"tronlink","version":"1.0"}>`.
  https://docs.tronlink.org/mobile/deeplink . Оговорка: с 08.2023 TronLink фильтрует сторонние
  deeplink по whitelist (https://github.com/tronprotocol/tronwallet-adapter/issues/30).
  Поэтому в UI рядом с QR стоит запасной путь: открыть TronLink, вкладка «Обзор/DApp»,
  вставить URL `https://pay.pxbt.app/admin`.

Провайдеры:
- EIP-6963: https://eips.ethereum.org/EIPS/eip-6963 (события `eip6963:requestProvider` / `eip6963:announceProvider`).
- EIP-1193 `personal_sign`, ошибка `4001` = user rejected: https://eips.ethereum.org/EIPS/eip-1193
- TronLink TIP-1102 `window.tron.request({method:'eth_requestAccounts'})`, 4001; `tronWeb.trx.signMessageV2`
  при отказе rejects строкой `'Confirmation declined by user'`:
  https://docs.tronlink.org/plugin-wallet/active-requests/ , https://docs.tronlink.org/reference/error-code-map/
- Reown AppKit: https://docs.reown.com/appkit/overview , JS core: https://docs.reown.com/appkit/javascript/core/installation
- Solana Wallet Adapter: https://github.com/anza-xyz/wallet-adapter ; Wallet Standard: https://github.com/wallet-standard/wallet-standard
- Phantom provider `connect()` / `signMessage(bytes,'utf8')`, 4001: https://docs.phantom.com/solana/signing-a-message

## Выбор и обоснование

1. **Расширение есть.** EVM: EIP-6963, затем `window.ethereum`. Tron: `window.tron`, затем `tronLink`/`tronWeb`.
   Solana: `phantom.solana`, затем `window.solana`. Порядок шагов: найти кошелёк, connect (адрес),
   nonce, подпись, verify. Nonce запрашивается только когда адрес уже получен, поэтому
   висящих nonce нет.
2. **Расширения нет.** Понятное сообщение и QR + ссылка deeplink на эту же страницу внутри
   мобильного кошелька. Там провайдер инжектирован, и работает тот же код из п.1. Никаких новых
   серверных компонентов, аккаунтов и зависимостей.
3. **Reown AppKit отложен.** Он единственный даёт подпись с телефона, не уходя со страницы десктопа.
   Но ему нужны регистрация внешнего аккаунта (projectId), npm-бандл в репо, где принципиально
   нет npm, и сторонний relay в критическом пути. Tron он всё равно не закрывает. Deeplink + QR
   решает задачу «подключить без расширения» за 0 и без нового аккаунта.
   Апгрейд-путь: если владелец захочет подписывать с телефона, не открывая страницу на нём,
   добавляем AppKit как четвёртую кнопку (CDN ESM `@reown/appkit` + projectId в env) для EVM/Solana.
4. **Сервер не меняется.** Проверка подписи уже прод-уровня. Сообщение подписи остаётся прежним.
   EVM `personal_sign` получает его как 0x-hex UTF-8 (рекомендация EIP-1193, иначе часть кошельков
   отвергает не-hex).

Не колхозим: discovery берём по стандартам (EIP-6963/TIP-1102), deeplink-форматы по докам кошельков,
QR из готовой MIT-библиотеки (vendored, как noble).
