/**
 * Replay реальной mainnet-выдачи TronGrid (USDT-TRC20) через матчер счетов — без сети и без денег.
 * Фикстура: test/fixtures_trongrid_usdt_mainnet.json (сырой ответ /v1/accounts/<a>/transactions/trc20).
 * Запуск: node test/test_trc20_replay.mjs
 */
import assert from 'node:assert';
import fs from 'node:fs';
import { PAIRS, CONFIG_KEY } from '../functions/lib/config.js';
import { tronMatchesFromTronGrid } from '../functions/lib/paycheck.js';
import * as invoiceApi from '../functions/api/invoice/[[id]].js';

const fx = JSON.parse(fs.readFileSync(new URL('./fixtures_trongrid_usdt_mainnet.json', import.meta.url), 'utf8'));
const pair = PAIRS['USDT-TRC20'];
assert.strictEqual(pair.token, 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', 'без env — mainnet USDT');
const real = fx.data.find((t) => t.value === '998500000'); // 998.5 USDT, tx 6a0601dd…
assert.ok(real, 'фикстура содержит реальный перевод');
const ADDR = real.to, TS = real.block_timestamp;

// 1) чистый матчер: счёт на ровно 998.500000, созданный до перевода — совпадает ровно этот tx
assert.deepStrictEqual(tronMatchesFromTronGrid(fx, pair, ADDR, '998500000', TS - 5 * 60_000), [{ tx: real.transaction_id, amount: 998.5 }]);
// сумма на микроюнит больше — нет совпадения
assert.deepStrictEqual(tronMatchesFromTronGrid(fx, pair, ADDR, '998500001', TS - 5 * 60_000), []);
// счёт создан позже перевода — старый перевод не засчитывается
assert.deepStrictEqual(tronMatchesFromTronGrid(fx, pair, ADDR, '998500000', TS + 5 * 60_000), []);
// другой адрес получателя / другой токен — нет
assert.deepStrictEqual(tronMatchesFromTronGrid(fx, pair, 'TQrY8try6YCHAEuZGB9puHKiQWy6iRfnCw', '998500000', 0), []);
assert.deepStrictEqual(tronMatchesFromTronGrid(fx, { ...pair, token: 'TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf' }, ADDR, '998500000', 0), []);

// 2) полный путь API: счёт pending -> PUT /status с replay-ответом TronGrid -> paid с этим tx
const m = new Map();
const env = { KV: { get: async (k) => m.get(k) ?? null, put: async (k, v) => void m.set(k, v), delete: async (k) => void m.delete(k) } };
m.set(CONFIG_KEY, JSON.stringify({ addresses: { tron: ADDR }, pairs: { 'USDT-TRC20': true } }));
m.set('invoice:replay1', JSON.stringify({ amount: '998.500000', dueMicro: '998500000', currency: 'USD', status: 'pending', createdMs: TS - 5 * 60_000 }));
await invoiceApi.onRequestPost({ env, params: { id: 'replay1' }, request: new Request('https://pay.pxbt.app/t', { method: 'POST', body: '{"pair":"USDT-TRC20"}' }) });
const realFetch = globalThis.fetch;
let asked = '';
globalThis.fetch = async (u) => { asked = String(u); return new Response(JSON.stringify(fx)); };
try {
  const r = await (await invoiceApi.onRequestPut({ env, params: { id: 'replay1' } })).json();
  assert.strictEqual(r.status, 'paid', JSON.stringify(r));
  assert.strictEqual(r.tx, real.transaction_id);
  assert.match(asked, /^https:\/\/api\.trongrid\.io\/v1\/accounts\/T\w+\/transactions\/trc20\?.*contract_address=TR7NHqje/);
  assert.strictEqual(JSON.parse(m.get('invoice:replay1')).status, 'paid');
  assert.strictEqual(m.get('paidtx:tron:' + real.transaction_id), 'replay1');
} finally { globalThis.fetch = realFetch; }

console.log('trc20 replay: all OK (' + real.transaction_id + ')');
