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
import { pairEndpoint, enabledPairs, defaultConfig, CONFIG_KEY } from '../functions/lib/config.js';

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

console.log('api tests: all OK');
