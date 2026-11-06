/**
 * Локальные интеграционные тесты API-логики (без Cloudflare): KV-заглушка в памяти.
 * Покрывают acceptance #2 (неверная подпись -> отказ) и #3 (клиент видит только включённые пары).
 * Запуск: node test/test_api.mjs
 */
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyWalletSignature } from '../functions/lib/wallet-verify.js';
import { pairEndpoint, enabledPairs, defaultConfig, CONFIG_KEY, PAIRS } from '../functions/lib/config.js';
import { toMicro } from '../functions/lib/paycheck.js';
import * as invoiceCreate from '../functions/api/invoice/create.js';
import * as invoiceApi from '../functions/api/invoice/[[id]].js';

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'vectors.json'), 'utf8'));

// --- KV-заглушка
function makeKV() {
  const m = new Map();
  return {
    async get(k) { return m.get(k) ?? null; },
    async put(k, v) { m.set(k, v); },
    async delete(k) { m.delete(k); },
  };
}

// --- поведение verify-эндпоинта (логика из functions/api/claim/verify.js, продублирована для теста вне workers-рантайма)
async function claimVerify(env, { chain, address, signature, nonce }) {
  const nonceKey = 'claim:' + nonce;
  const raw = await env.get(nonceKey);
  if (!raw) return { ok: false, error: 'nonce expired or unknown' };
  const { chain: nonceChain } = JSON.parse(raw);
  if (nonceChain !== chain) return { ok: false, error: 'chain mismatch' };
  const message = `pay.pxbt.app: claim ${nonce}\nвладелец pxbt.app`;
  try {
    const res = verifyWalletSignature({ chain, message, signature, address });
    await env.delete(nonceKey);
    const cfg = JSON.parse((await env.get(CONFIG_KEY)) || '{"addresses":{},"pairs":{}}');
    cfg.addresses[chain === 'tron' ? 'tron' : chain === 'solana' ? 'solana' : 'evm'] = res.address;
    await env.put(CONFIG_KEY, JSON.stringify(cfg));
    return { ok: true, address: res.address, chain };
  } catch (e) {
    return { ok: false, error: 'signature verification failed', detail: String(e.message || e) };
  }
}

// --- acceptance #1: подпись сохраняет адрес без ручного ввода
{
  const kv = makeKV();
  await kv.put('claim:ab12cd34ef56', JSON.stringify({ chain: 'evm', ts: Date.now() }));
  const r = await claimVerify(kv, { chain: 'evm', address: V.evm.addr, signature: V.evm.sig, nonce: 'ab12cd34ef56' });
  assert.strictEqual(r.ok, true, 'verify ok: ' + JSON.stringify(r));
  const cfg = JSON.parse(await kv.get(CONFIG_KEY));
  assert.strictEqual(cfg.addresses.evm, V.evm.addr.toLowerCase());
  // nonce сгорел
  const r2 = await claimVerify(kv, { chain: 'evm', address: V.evm.addr, signature: V.evm.sig, nonce: 'ab12cd34ef56' });
  assert.strictEqual(r2.ok, false, 'nonce single-use');
}

// --- acceptance #2: неверная подпись -> отказ, адрес НЕ сохранён
{
  const kv = makeKV();
  await kv.put('claim:ab12cd34ef56', JSON.stringify({ chain: 'tron', ts: Date.now() }));
  const r = await claimVerify(kv, { chain: 'tron', address: V.tron.addr, signature: V.tron.sig.slice(0, -4) + 'beef', nonce: 'ab12cd34ef56' });
  assert.strictEqual(r.ok, false, 'bad sig rejected');
  const cfg = JSON.parse((await kv.get(CONFIG_KEY)) || JSON.stringify(defaultConfig()));
  assert.strictEqual(cfg.addresses.tron, undefined, 'address NOT saved on bad sig');
}

// --- acceptance #3: клиент видит только включённые пары
{
  const cfg = {
    addresses: { evm: '0xabc', tron: 'TQrY8try6YCHAEuZGB9puHKiQWy6iRfnCw' },
    pairs: { 'USDT-TRC20': true, 'USDT-ERC20': false, 'USDT-BEP20': true },
  };
  const vis = enabledPairs(cfg).map((p) => p.id);
  assert.deepStrictEqual(vis, ['USDT-TRC20', 'USDT-BEP20'], 'only enabled pairs');
  assert.strictEqual(pairEndpoint(cfg, 'USDT-ERC20'), null, 'disabled pair -> null');
  assert.strictEqual(pairEndpoint(cfg, 'USDT-POLY'), null, 'enabled but no evm? -> evm is set; poly shares evm addr but pair off');
}

// --- paycheck: amountMatches через трон-заглушку не тестируем сетью; проверяем pure-функции
{
  // конфиг без адресов — пустой список пар
  assert.deepStrictEqual(enabledPairs(defaultConfig()), []);
}

// --- оплата: уникальная сумма + реестр tx (ревью раунд 1)
{
  const kv = makeKV();
  const env = { KV: kv };
  const TRON = 'TQrY8try6YCHAEuZGB9puHKiQWy6iRfnCw';
  await kv.put(CONFIG_KEY, JSON.stringify({ addresses: { tron: TRON }, pairs: { 'USDT-TRC20': true } }));
  const mk = async (amount) => (await (await invoiceCreate.onRequestPost({ env, request: new Request('http://x', { method: 'POST', body: JSON.stringify({ amount }) }) })).json()).id;
  const a = await mk(1), b = await mk(1);
  const inv = async (id) => JSON.parse(await kv.get('invoice:' + id));
  const ia = await inv(a);
  assert.match(ia.amount, /^1\.00\d{4}$/, 'сумма с хвостом: ' + ia.amount);
  assert.ok(Number(ia.dueMicro) > 1_000_000 && Number(ia.dueMicro) < 1_001_000);
  for (const id of [a, b]) await invoiceApi.onRequestPost({ env, params: { id }, request: new Request('http://x', { method: 'POST', body: '{"pair":"USDT-TRC20"}' }) });

  let transfers = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ token_transfers: transfers }));
  const tr = (tx, quant) => ({ transaction_id: tx, to_address: TRON, quant: String(quant), confirmed: true, finalResult: 'SUCCESS', block_ts: Date.now(), tokenInfo: { tokenId: PAIRS['USDT-TRC20'].token, tokenDecimal: 6 } });
  const check = async (id) => (await invoiceApi.onRequestPut({ env, params: { id } })).json();
  try {
    // крупный чужой перевод (147 USDT) и ровно «1.000000» без хвоста не закрывают счёт на 1
    transfers = [tr('big', 147_000_000), tr('round', 1_000_000)];
    assert.strictEqual((await check(a)).status, 'pending', 'чужая сумма не закрывает счёт');
    // один tx на сумму счёта A: A paid, B (другой хвост) нет
    transfers = [tr('t1', ia.dueMicro)];
    const ra = await check(a);
    assert.strictEqual(ra.status, 'paid'); assert.strictEqual(ra.tx, 't1');
    assert.strictEqual((await check(b)).status, 'pending', 'B не закрыт переводом A');
    // даже при совпадении суммы tx, уже привязанный к другому счёту, не засчитывается
    const ib2 = await inv(b); ib2.dueMicro = ia.dueMicro; await kv.put('invoice:' + b, JSON.stringify(ib2));
    assert.strictEqual((await check(b)).status, 'pending', 'один tx не закрывает два счёта');
    assert.strictEqual(await kv.get('paidtx:tron:t1'), a);
    transfers.push(tr('t2', ia.dueMicro));
    assert.strictEqual((await check(b)).tx, 't2', 'свой tx закрывает B');
    assert.strictEqual((await check(a)).tx, 't1', 'повторная проверка A стабильна');
  } finally { globalThis.fetch = realFetch; }
}

// --- decimals: BSC USDT 18 знаков, пыль мельче микроюнита не совпадает
assert.strictEqual(toMicro('1000123000000000000', 18), 1_000_123n);
assert.strictEqual(toMicro('1000123000000000001', 18), null);
assert.strictEqual(PAIRS['USDC-BASE'].chain, 'base');

console.log('api tests: all OK');
