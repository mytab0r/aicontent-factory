/**
 * e2e публичных страниц pay.pxbt.app (лендинг + /u/<id>): настоящий сервер (deploy/pay-page/server.mjs),
 * настоящий Chromium. Проверяет: кнопка WalletConnect на лендинге открывает модалку; /u/<id> показывает
 * сети и монеты, смена сети перерисовывает монеты; неизвестный id = 404; вёрстка 375px без горизонтального скролла.
 * Запуск: node test/e2e/user.e2e.mjs   (CDP_URL/E2E_HOST — как в admin.e2e.mjs)
 */
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';
import { makeServer } from '../../deploy/pay-page/server.mjs';

const SSO = 'e2e-sso-secret';
const HOST = process.env.E2E_HOST || '127.0.0.1';
const EVM = '0x1234567890abcdef1234567890abcdef12345678';
const TRON = 'TQrY8try6YCHAEuZGB9puHKiQWy6iRfnCw';
const browser = process.env.CDP_URL ? await chromium.connectOverCDP(process.env.CDP_URL) : await chromium.launch();

async function setup({ viewport, projectId = 'e2e-project-id', stubAppkit = true } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pay-u-'));
  const srv = makeServer({ dataDir: dir, ownerEmail: 'o@example.com', proxySecret: SSO, extraEnv: { REOWN_PROJECT_ID: projectId } });
  await new Promise((r) => srv.listen(0, '0.0.0.0', r));
  const base = `http://${HOST}:${srv.address().port}`;
  const ctx = await browser.newContext({ ...(viewport ? { viewport } : {}) });
  if (stubAppkit) {
    // AppKit грузится с esm.sh — в e2e сеть не нужна; подменяем window.__appkit, страница его уважает.
    await ctx.addInitScript(() => {
      window.__appkit = { modal: { open: async () => { window.__modalOpen = true; }, close: async () => { window.__modalOpen = false; }, getState: () => ({ open: !!window.__modalOpen }) } };
    });
  }
  // Внешние запросы режем: страница обязана работать, даже если CDN с QR-библиотекой недоступен.
  await ctx.route('**/*', (route) => (route.request().url().includes(HOST) ? route.continue() : route.abort()));
  const page = await ctx.newPage();
  page.setDefaultTimeout(10_000);
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const close = async () => { await ctx.close(); await new Promise((r) => srv.close(r)); fs.rmSync(dir, { recursive: true, force: true }); };
  return { page, base, errors, close };
}

const results = [];
async function scenario(name, fn) {
  const t0 = Date.now();
  try { await fn(); results.push(['ok', name]); console.log(`ok   ${name} (${Date.now() - t0} ms)`); }
  catch (e) { results.push(['FAIL', name]); console.log(`FAIL ${name}\n     ${String(e.message).split('\n').slice(0, 6).join('\n     ')}`); }
}

// U1: лендинг отдаётся, кнопка WalletConnect открывает модалку
await scenario('U1 лендинг: кнопка WalletConnect открывает модалку', async () => {
  const env = await setup();
  try {
    await env.page.goto(env.base + '/', { waitUntil: 'domcontentloaded' });
    await env.page.waitForSelector('#wc');
    assert.strictEqual(await env.page.locator('#wc').isVisible(), true, 'кнопка видна');
    await env.page.click('#wc');
    await env.page.waitForFunction(() => window.__modalOpen === true, null, { timeout: 10_000 });
    assert.deepStrictEqual(env.errors, [], 'нет необработанных исключений');
  } finally { await env.close(); }
});

// U2: без projectId кнопка скрыта и сказано почему (никакой висящей кнопки без действия)
await scenario('U2 лендинг без projectId: кнопки нет, причина показана', async () => {
  const env = await setup({ projectId: '' , stubAppkit: false });
  try {
    await env.page.goto(env.base + '/', { waitUntil: 'domcontentloaded' });
    await env.page.waitForSelector('#wcstate');
    assert.strictEqual(await env.page.locator('#wc').isVisible(), false, 'кнопка скрыта');
    assert.match(await env.page.locator('#wcstate').textContent(), /WalletConnect не настроен/);
    assert.deepStrictEqual(env.errors, []);
  } finally { await env.close(); }
});

// U3: /u/<tron-адрес> показывает сети, выбор сети даёт адрес и QR
await scenario('U3 /u/<tron>: сети, адрес, QR', async () => {
  const env = await setup();
  try {
    const r = await env.page.goto(env.base + '/u/' + TRON, { waitUntil: 'domcontentloaded' });
    assert.strictEqual(r.status(), 200);
    assert.match(await env.page.locator('#opts').textContent(), /USDT · Tron \(TRC20\)/);
    await env.page.locator('#opts button', { hasText: 'Tron' }).first().click();
    assert.strictEqual((await env.page.locator('#addr').textContent()).trim(), TRON);
    // QR — из CDN-библиотеки; без сети страница обязана остаться рабочей, поэтому проверяем при наличии.
    if (await env.page.evaluate(() => typeof qrcode === 'function')) {
      assert.match(await env.page.locator('#qr').innerHTML(), /<img/i, 'QR отрисован');
    }
    assert.match(await env.page.locator('.warn').textContent(), /ТОЛЬКО Tron \(TRC20\)/, 'для не-EVM предупреждение про сеть');
    assert.deepStrictEqual(env.errors, [], 'нет необработанных исключений');
  } finally { await env.close(); }
});

// U4: /u/<evm-адрес> — один адрес на все EVM-сети, смена сети перерисовывает список монет
await scenario('U4 /u/<evm>: смена сети обновляет монеты', async () => {
  const env = await setup();
  try {
    const r = await env.page.goto(env.base + '/u/' + EVM, { waitUntil: 'domcontentloaded' });
    assert.strictEqual(r.status(), 200);
    const nets = await env.page.locator('#opts button').allTextContents();
    assert.ok(nets.length >= 5, 'все EVM-сети, got ' + nets.join('|'));
    assert.ok(!nets.some((t) => /Tron|Solana|Bitcoin|TON/.test(t)), 'не-EVM сети скрыты для EVM-адреса: ' + nets.join('|'));
    // Ethereum: USDT и USDC
    await env.page.locator('#opts button', { hasText: 'Ethereum' }).click();
    assert.deepStrictEqual(await env.page.locator('#toks button').allTextContents(), ['USDT', 'USDC']);
    assert.match(await env.page.locator('.warn').textContent(), /USDT/);
    // Base: нативного USDT нет -> остаётся только USDC
    await env.page.locator('#opts button', { hasText: 'Base' }).click();
    assert.deepStrictEqual(await env.page.locator('#toks button').allTextContents(), ['USDC']);
    assert.match(await env.page.locator('.warn').textContent(), /USDC/, 'предупреждение следует за выбранной монетой');
    assert.strictEqual((await env.page.locator('#addr').textContent()).trim(), EVM);
    assert.deepStrictEqual(env.errors, []);
  } finally { await env.close(); }
});

// U5: неизвестный id -> 404-страница, не пустой экран
await scenario('U5 /u/<несуществующий id>: 404', async () => {
  const env = await setup();
  try {
    const r = await env.page.goto(env.base + '/u/zzzznotanaddresszzzzzzzzzzzz', { waitUntil: 'domcontentloaded' });
    assert.strictEqual(r.status(), 404);
    assert.match(await env.page.locator('body').textContent(), /Страница не найдена/);
    assert.deepStrictEqual(env.errors, []);
  } finally { await env.close(); }
});

// U6: мобильная вёрстка 375px — ни на лендинге, ни на /u нет горизонтального скролла
await scenario('U6 375px: горизонтального скролла нет', async () => {
  const env = await setup({ viewport: { width: 375, height: 812 } });
  try {
    for (const url of ['/', '/u/' + TRON, '/u/' + EVM]) {
      await env.page.goto(env.base + url, { waitUntil: 'domcontentloaded' });
      if (url.startsWith('/u/')) {
        await env.page.locator('#opts button').first().click();
        await env.page.waitForFunction(() => document.getElementById('addr').textContent.trim().length > 10);
      }
      const over = await env.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      assert.ok(over <= 0, `${url}: переполнение по ширине ${over}px`);
    }
    assert.deepStrictEqual(env.errors, []);
  } finally { await env.close(); }
});

await browser.close();
const bad = results.filter(([s]) => s !== 'ok');
console.log(`\n${results.length - bad.length}/${results.length} сценариев ok`);
process.exit(bad.length ? 1 : 0);
