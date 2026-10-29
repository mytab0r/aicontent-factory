/**
 * e2e /admin: подключение EVM / Tron / Solana кошельков (docs/pay/spec.md, S1–S5).
 * Настоящий сервер (deploy/pay-page/server.mjs, вход через SSO-заголовок), настоящий Chromium,
 * инжектированные кошельки подписывают реальными ключами (vendored noble) — сервер проверяет
 * подпись тем же verifyWalletSignature, что и в проде.
 * Запуск: node test/e2e/admin.e2e.mjs
 *   CDP_URL=http://host:9222 E2E_HOST=<ip этой машины>  — внешний Chrome вместо chromium.launch().
 */
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';
import { makeServer } from '../../deploy/pay-page/server.mjs';
import { sha256, sha512 } from '../../functions/vendor/noble/hashes/sha2.js';
import { keccak_256 } from '../../functions/vendor/noble/hashes/sha3.js';
import { hmac } from '../../functions/vendor/noble/hashes/hmac.js';
import * as secp from '../../functions/vendor/noble/secp256k1/secp256k1.js';
import * as ed from '../../functions/vendor/noble/ed25519/ed25519.js';

secp.hashes.sha256 = sha256;
secp.hashes.hmacSha256 = (k, m) => hmac(sha256, k, m);
ed.hashes.sha512 = sha512;

// ---------- тестовые ключи и подпись (Node-сторона) ----------
const enc = new TextEncoder();
const hex = (b) => Buffer.from(b).toString('hex');
const B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function b58(bytes) {
  let n = BigInt('0x' + (hex(bytes) || '0')), s = '';
  while (n > 0n) { s = B58[Number(n % 58n)] + s; n /= 58n; }
  for (const b of bytes) { if (b) break; s = '1' + s; }
  return s;
}
const SECP_PRIV = Uint8Array.from(Buffer.from('4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318', 'hex'));
const ED_PRIV = Uint8Array.from(Buffer.from('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60', 'hex'));
const pubHash = keccak_256(secp.getPublicKey(SECP_PRIV, false).slice(1)).slice(12);
const EVM_ADDR = '0x' + hex(pubHash);
const tronPayload = Uint8Array.from([0x41, ...pubHash]);
const TRON_ADDR = b58(Uint8Array.from([...tronPayload, ...sha256(sha256(tronPayload)).slice(0, 4)]));
const SOL_ADDR = b58(ed.getPublicKey(ED_PRIV));
const ADDR = { evm: EVM_ADDR, tron: TRON_ADDR, solana: SOL_ADDR };

function secpSign(prefix, msgBytes) {
  const d = keccak_256(Uint8Array.from([...enc.encode(prefix + msgBytes.length), ...msgBytes]));
  const rec = secp.sign(d, SECP_PRIV, { prehash: false, format: 'recovered' }); // [v, r, s]
  return '0x' + hex(rec.slice(1)) + (rec[0] + 27).toString(16);
}
// msg: {hex} (EVM personal_sign) | {text} (Tron) | {bytes} (Solana)
function walletSign(chain, msg) {
  const bytes = msg.hex ? Uint8Array.from(Buffer.from(msg.hex.replace(/^0x/, ''), 'hex'))
    : msg.text != null ? enc.encode(msg.text) : Uint8Array.from(msg.bytes);
  if (chain === 'evm') return secpSign('\x19Ethereum Signed Message:\n', bytes);
  if (chain === 'tron') return secpSign('\x19TRON Signed Message:\n', bytes);
  return Array.from(ed.sign(bytes, ED_PRIV));
}

// ---------- инжектированные кошельки (браузерная сторона) ----------
// cfg: { wallets: bool, reject: 'connect'|'sign'|null, addr }
function injectWallets(cfg) {
  if (!cfg.wallets) return;
  const err4001 = () => Object.assign(new Error('User rejected the request.'), { code: 4001 });
  // EVM: только EIP-6963, без window.ethereum
  const evm = {
    async request({ method, params }) {
      if (method === 'eth_requestAccounts' || method === 'eth_accounts') {
        if (cfg.reject === 'connect') throw err4001();
        return [cfg.addr.evm];
      }
      if (method === 'personal_sign') {
        if (cfg.reject === 'sign') throw err4001();
        const m = params[0];
        const msg = /^0x[0-9a-f]*$/i.test(m) ? { hex: m } : { text: m };
        return window.__walletSign('evm', msg);
      }
      throw Object.assign(new Error('unsupported ' + method), { code: 4200 });
    },
    on() {}, removeListener() {},
  };
  const info = Object.freeze({ uuid: '7c1b1c1e-0000-4000-8000-000000000001', name: 'E2E Wallet', icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"/>', rdns: 'test.e2e.wallet' });
  const announce = () => window.dispatchEvent(new CustomEvent('eip6963:announceProvider', { detail: Object.freeze({ info, provider: evm }) }));
  window.addEventListener('eip6963:requestProvider', announce);
  announce();
  // Tron: TIP-1102 window.tron, tronWeb появляется только после авторизации
  const tronWeb = {
    ready: true,
    defaultAddress: { base58: cfg.addr.tron },
    trx: {
      async signMessageV2(text) {
        if (cfg.reject === 'sign') throw 'Confirmation declined by user';
        return window.__walletSign('tron', { text: String(text) });
      },
    },
  };
  window.tron = {
    isTronLink: true,
    tronWeb: false,
    async request({ method }) {
      if (method !== 'eth_requestAccounts') throw Object.assign(new Error('unsupported'), { code: 4200 });
      if (cfg.reject === 'connect') throw err4001();
      this.tronWeb = tronWeb;
      return { code: 200, message: 'ok' };
    },
  };
  // Solana: Phantom
  const publicKey = { toString: () => cfg.addr.solana, toBase58: () => cfg.addr.solana };
  window.phantom = {
    solana: {
      isPhantom: true,
      publicKey: null,
      async connect() {
        if (cfg.reject === 'connect') throw err4001();
        this.publicKey = publicKey;
        return { publicKey };
      },
      async signMessage(bytes) {
        if (cfg.reject === 'sign') throw err4001();
        const sig = await window.__walletSign('solana', { bytes: Array.from(bytes) });
        return { signature: new Uint8Array(sig), publicKey };
      },
    },
  };
}

// ---------- окружение ----------
const SSO = 'e2e-sso-secret';
const browser = process.env.CDP_URL ? await chromium.connectOverCDP(process.env.CDP_URL) : await chromium.launch();
const HOST = process.env.E2E_HOST || '127.0.0.1';

async function setup({ wallets = true, reject = null, userAgent } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pay-e2e-'));
  const srv = makeServer({ dataDir: dir, ownerEmail: 'o@example.com', proxySecret: SSO, extraEnv: { REOWN_PROJECT_ID: 'e2e-project-id' } });
  await new Promise((r) => srv.listen(0, '0.0.0.0', r));
  const base = `http://${HOST}:${srv.address().port}`;
  const ctx = await browser.newContext({ extraHTTPHeaders: { 'x-pay-proxy-auth': SSO }, ...(userAgent ? { userAgent } : {}) });
  await ctx.exposeFunction('__walletSign', walletSign);
  await ctx.addInitScript(injectWallets, { wallets, reject, addr: ADDR });
  const page = await ctx.newPage();
  page.setDefaultTimeout(10_000);
  const errors = [], nonceReqs = [], verifyBodies = [], failed = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('request', (r) => {
    if (r.url().endsWith('/api/claim/nonce')) nonceReqs.push(r);
    if (r.url().endsWith('/api/claim/verify')) verifyBodies.push(r.postData());
  });
  page.on('requestfailed', (r) => failed.push(r.url()));
  await page.goto(base + '/admin');
  const close = async () => { await ctx.close(); await new Promise((r) => srv.close(r)); fs.rmSync(dir, { recursive: true, force: true }); };
  return { page, base, errors, nonceReqs, verifyBodies, failed, close };
}

const logHas = (page, text, timeout = 10_000) =>
  page.waitForFunction((t) => (document.getElementById('log')?.textContent || '').includes(t), text, { timeout });
const addresses = (page) => page.locator('#addresses').textContent();
const addrHas = (page, text, what) =>
  page.waitForFunction((t) => (document.getElementById('addresses')?.textContent || '').includes(t), text, { timeout: 10_000 })
    .catch((e) => { throw new Error(what + ': ' + e.message); });
const shown = (chain, addr) => chain + ': ' + (chain === 'evm' ? addr.toLowerCase() : addr);
const noPageErrors = (env, what) => assert.deepStrictEqual(env.errors, [], what + ': необработанные исключения на странице');
const notDefined = async (env) => assert.doesNotMatch(await env.page.locator('#log').textContent(), /is not defined/);

const CHAINS = ['evm', 'tron', 'solana'];
const results = [];
async function scenario(name, fn) {
  const t0 = Date.now();
  try { await fn(); results.push(['ok', name]); console.log(`ok   ${name} (${Date.now() - t0} ms)`); }
  catch (e) { results.push(['FAIL', name]); console.log(`FAIL ${name}\n     ${String(e.message).split('\n').slice(0, 6).join('\n     ')}`); }
}

// S1: успешная привязка + адрес в списке после перезагрузки
await scenario('S1 одна кнопка: все 3 адреса, видны после reload', async () => {
  const env = await setup();
  try {
    await env.page.click('#connect-all');
    for (const chain of CHAINS) {
      await logHas(env.page, `✔ ${chain}: адрес сохранён ${shown(chain, ADDR[chain]).slice(chain.length + 2)}`);
      await addrHas(env.page, shown(chain, ADDR[chain]), 'адрес в #addresses');
    }
    await env.page.reload();
    for (const chain of CHAINS) await addrHas(env.page, shown(chain, ADDR[chain]), 'адрес после reload');
    noPageErrors(env, 'S1');
  } finally { await env.close(); }
});

// S2: кошелька нет — понятное сообщение с путём (dApp-браузер кошелька), ни одного nonce
for (const chain of CHAINS) await scenario(`S2 ${chain}: кошелька нет`, async () => {
  const env = await setup({ wallets: false });
  try {
    await env.page.click('#connect-all');
    await logHas(env.page, '✘ кошелёк не найден');
    await notDefined(env);
    assert.strictEqual(env.nonceReqs.length, 0, 'без кошелька nonce не запрашивается');
    noPageErrors(env, chain);
  } finally { await env.close(); }
});

// S3: подпись отклонена
for (const chain of CHAINS) await scenario(`S3 ${chain}: подпись отклонена`, async () => {
  const env = await setup({ reject: 'sign' });
  try {
    await env.page.evaluate((c) => claimChain(c), chain);
    await logHas(env.page, `✘ ${chain}: подпись отклонена в кошельке`);
    assert.ok(!(await addresses(env.page)).includes(shown(chain, ADDR[chain])), 'адрес не сохранён');
    noPageErrors(env, chain);
  } finally { await env.close(); }
});

// S3b: подключение отклонено — nonce не запрашивается
for (const chain of CHAINS) await scenario(`S3b ${chain}: подключение отклонено`, async () => {
  const env = await setup({ reject: 'connect' });
  try {
    await env.page.evaluate((c) => claimChain(c), chain);
    await logHas(env.page, `✘ ${chain}: подключение отклонено в кошельке`);
    assert.strictEqual(env.nonceReqs.length, 0, 'nonce не запрашивается');
    noPageErrors(env, chain);
  } finally { await env.close(); }
});

// S4a: /api/claim/nonce обрывается
for (const chain of CHAINS) await scenario(`S4a ${chain}: nonce — сеть недоступна`, async () => {
  const env = await setup();
  try {
    await env.page.route('**/api/claim/nonce', (r) => r.abort('failed'));
    await env.page.evaluate((c) => claimChain(c), chain);
    await logHas(env.page, `✘ ${chain}: сеть недоступна`);
    noPageErrors(env, chain);
  } finally { await env.close(); }
});

// S4b: /api/claim/verify не отвечает — тайм-аут ≤15 с, запрос отменён, кнопка disabled на время claim
await scenario('S4b evm: verify не отвечает', async () => {
  const env = await setup();
  try {
    const seen = new Promise((res) => env.page.route('**/api/claim/verify', () => res())); // не отвечаем
    const t0 = Date.now();
    await env.page.evaluate(() => { claimChain('evm'); }); // не ждём завершения: клик по кнопке тоже не ждёт
    await seen;
    assert.ok(await env.page.locator('#connect-all').isDisabled(), 'кнопка disabled, пока claim идёт');
    await logHas(env.page, '✘ evm: сеть недоступна', 20_000);
    assert.ok(Date.now() - t0 <= 17_000, 'тайм-аут ≤15 с');
    await env.page.waitForFunction(() => !document.getElementById('connect-all').disabled, null, { timeout: 2000 });
    assert.ok(env.failed.some((u) => u.endsWith('/api/claim/verify')), 'запрос отменён клиентом');
    noPageErrors(env, 'evm');
  } finally { await env.close(); }
});

// S6: WC-модалку закрыли — кнопка снова активна <2 c (раньше висела disabled до 180 с)
await scenario('S6 evm: закрыл модалку — кнопка активна <2 с', async () => {
  const env = await setup({ wallets: false });
  try {
    // AppKit может не загрузиться (в CI-образе esm.sh недоступен) — тогда ставим stub-модалку с тем же контрактом getState/open/close.
    await env.page.waitForFunction(() => !!window.__appkit, null, { timeout: 30_000 }).catch(async () => {
      await env.page.evaluate(() => {
        delete window.__appkitError;
        const st = { open: false };
        window.__appkit = {
          modal: {
            getState: () => st,
            open: async () => { st.open = true; },
            close: async () => { st.open = false; },
          },
        };
      });
    });
    await env.page.click('#connect-all');
    await logHas(env.page, '✘ кошелёк не найден — открываю WalletConnect');
    await env.page.waitForFunction(() => window.__appkit.modal.getState().open, null, { timeout: 20_000 });
    assert.ok(await env.page.evaluate(() => document.getElementById('connect-all').disabled), 'кнопка disabled, пока модалка открыта');
    await env.page.evaluate(() => window.__appkit.modal.close());
    const t0 = Date.now();
    await env.page.waitForFunction(() => !document.getElementById('connect-all').disabled, null, { timeout: 2000 });
    assert.ok(Date.now() - t0 < 2000, 'кнопка активна <2 с после закрытия модалки');
    await logHas(env.page, '✘ evm: подключение отклонено в кошельке');
    noPageErrors(env, 'S6');
  } finally { await env.close(); }
});

// S7: iOS Telegram in-app browser — сразу подсказка, WC-модалка не открывается
await scenario('S7 evm: Telegram UA — сразу подсказка без модалки', async () => {
  const env = await setup({ wallets: false });
  try {
    await env.page.evaluate(() => {
      Object.defineProperty(navigator, 'userAgent', { get: () => 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Telegram-iOS/10.0' });
    });
    await env.page.evaluate(() => claimChain('evm'));
    await logHas(env.page, '✘ evm: кошелёк не найден');
    assert.ok(await env.page.locator('#nowallet').isVisible(), 'подсказка видна');
    assert.match(await env.page.locator('#nowallet-msg').textContent(), /pay\.pxbt\.app\/admin в SafePal → Discover/);
    assert.ok(!(await env.page.evaluate(() => window.__appkit && window.__appkit.modal.getState().open)), 'модалка не открывается');
    noPageErrors(env, 'S7');
  } finally { await env.close(); }
});

// S8: Telegram WebView / iOS без window.ethereum — подсказка SafePal видна сразу после загрузки, без клика
const IOS_SAFARI = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
const IOS_TG = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Telegram-iOS/10.0';
for (const [name, userAgent] of [['iOS без window.ethereum', IOS_SAFARI], ['Telegram UA', IOS_TG]]) {
  await scenario(`S8 ${name}: подсказка SafePal → Discover сразу при загрузке`, async () => {
    const env = await setup({ wallets: false, userAgent });
    try {
      await env.page.waitForFunction(() => !document.getElementById('nowallet').hidden, null, { timeout: 3000 });
      assert.match(await env.page.locator('#nowallet-msg').textContent(), /pay\.pxbt\.app\/admin в SafePal → Discover/);
      noPageErrors(env, 'S8');
    } finally { await env.close(); }
  });
}
// S8b: десктоп без кошелька — подсказка при загрузке НЕ показывается (не шумим зря)
await scenario('S8b desktop: подсказки при загрузке нет', async () => {
  const env = await setup({ wallets: false });
  try {
    await env.page.waitForTimeout(1000);
    assert.ok(await env.page.locator('#nowallet').isHidden(), 'подсказка скрыта на десктопе');
  } finally { await env.close(); }
});

// S5: повторный nonce отклоняется, второй клик берёт новый nonce
await scenario('S5 evm: повторный nonce', async () => {
  const env = await setup();
  try {
    await env.page.evaluate(() => claimChain('evm'));
    await logHas(env.page, '✔ evm: адрес сохранён');
    const first = JSON.parse(env.verifyBodies[0]);
    const replay = await fetch(env.base.replace(HOST, '127.0.0.1') + '/api/claim/verify', {
      method: 'POST', headers: { 'content-type': 'application/json', 'x-pay-proxy-auth': SSO }, body: env.verifyBodies[0],
    });
    assert.strictEqual(replay.status, 400);
    assert.strictEqual((await replay.json()).error, 'nonce expired or unknown');
    await env.page.waitForFunction(() => !document.getElementById('connect-all').disabled);
    await env.page.evaluate(() => claimChain('evm'));
    await env.page.waitForFunction(() => (document.getElementById('log').textContent.match(/✔ evm: адрес сохранён/g) || []).length === 2, null, { timeout: 10_000 });
    const second = JSON.parse(env.verifyBodies[1]);
    assert.notStrictEqual(second.nonce, first.nonce, 'новый nonce');
    noPageErrors(env, 'evm');
  } finally { await env.close(); }
});

await browser.close();
const bad = results.filter(([s]) => s !== 'ok');
console.log(`\n${results.length - bad.length}/${results.length} сценариев ok`);
process.exit(bad.length ? 1 : 0);
