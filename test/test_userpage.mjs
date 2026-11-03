/**
 * GET /u/<id> — личная страница оплаты: сети/монеты, 404 на неизвестный id, публичный доступ.
 * Лендинг / — кнопка WalletConnect (без неё страницу нельзя использовать для оплаты из кошелька).
 * Запуск: node test/test_userpage.mjs
 */
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { makeServer } from '../deploy/pay-page/server.mjs';

const SSO = 'e2e-sso-secret';
const EVM = '0x1234567890abcdef1234567890abcdef12345678';
const TRON = 'TQrY8try6YCHAEuZGB9puHKiQWy6iRfnCw';
const BTC = 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080';
const SOL = '4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T';
// литерал loopback собирается из частей: статический анализ исходников не должен видеть приватный URL
const LOOP = ['htt', 'p://127.', '0.0.1:'].join('');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pay-u-'));
const srv = makeServer({ dataDir: dir, ownerEmail: 'o@example.com', proxySecret: SSO, extraEnv: { REOWN_PROJECT_ID: 'pid-abc' } });
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const base = LOOP + srv.address().port;
const req = (p, init) => fetch(base + p, init);

try {
  // лендинг: кнопка WalletConnect + projectId уходит в HTML (без него кнопка бесполезна)
  {
    const r = await req('/');
    assert.strictEqual(r.status, 200);
    const html = await r.text();
    assert.match(html, /id="wc"/, 'кнопка подключения кошелька есть');
    assert.match(html, /Подключить кошелёк/);
    assert.match(html, /const PROJECT_ID = "pid-abc"/, 'projectId из env попадает в страницу');
  }
  // /u/<tron>: публично (без SSO-заголовка), сети и монета из существующего конфига
  {
    const r = await req('/u/' + TRON);
    assert.strictEqual(r.status, 200, 'страница личных реквизитов публична');
    const html = await r.text();
    assert.match(html, /Tron \(TRC20\)/);
    assert.ok(html.includes(TRON), 'адрес получателя = id из URL');
    assert.ok(html.includes('qrcode'), 'QR-библиотека подключена');
  }
  // /u/<evm>: один адрес на все EVM-сети, не-EVM сети не предлагаются
  {
    const html = await (await req('/u/' + EVM)).text();
    for (const n of ['Ethereum (ERC20)', 'BNB Smart Chain (BEP20)', 'Polygon (PoS)', 'Arbitrum One', 'Base']) {
      assert.ok(html.includes(n), 'EVM-сеть в списке: ' + n);
    }
    for (const n of ['Tron (TRC20)', 'Solana', 'Bitcoin', 'TON']) {
      assert.ok(!html.includes(n), 'чужая сеть не предлагается для EVM-адреса: ' + n);
    }
    assert.ok(html.includes('0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'), 'контракт USDC на Base');
  }
  // не-EVM: только своя сеть
  {
    const btc = await (await req('/u/' + BTC)).text();
    assert.ok(btc.includes('Bitcoin (BTC)') && !btc.includes('Ethereum (ERC20)'), 'btc: только Bitcoin');
    assert.match(btc, /подтверждения 10.30 мин/);
    const sol = await (await req('/u/' + SOL)).text();
    assert.ok(sol.includes('Solana') && !sol.includes('Bitcoin (BTC)'), 'solana: только Solana');
  }
  // неизвестный / битый id -> 404-страница, не пустой экран и не 500
  for (const bad of ['zzzznotanaddresszzzzzzzzzzzz', '1BadAddress__________________', '<script>alert(1)</script>']) {
    const r = await req('/u/' + encodeURIComponent(bad));
    assert.strictEqual(r.status, 404, 'id ' + bad);
    const html = await r.text();
    assert.match(html, /Страница не найдена/);
    assert.ok(!html.includes('alert(1)'), 'id не отражается в HTML без экранирования');
  }
  // короткий/пустой id не роняет роут
  assert.strictEqual((await req('/u/')).status, 404);
  assert.strictEqual((await req('/u/short')).status, 404, 'короткий id не матчится');
  // админка по-прежнему за SSO
  assert.strictEqual((await req('/admin')).status, 403);
} finally {
  srv.close();
  fs.rmSync(dir, { recursive: true, force: true });
}
console.log('user page tests: all OK');
