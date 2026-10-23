/**
 * Replay реальной mainnet-транзакции USDT-TRC20 (fixtures/tron_usdt_mainnet_tx.json, снята с TronGrid/Tronscan)
 * через настоящий путь API: create -> pay(USDT-TRC20) -> status. Сеть не трогаем: fetch отдаёт fixture.
 * Запуск: node test/test_tron_replay.mjs
 */
import assert from 'node:assert';
import fs from 'node:fs';
import { CONFIG_KEY, PAIRS } from '../functions/lib/config.js';
import * as invoiceCreate from '../functions/api/invoice/create.js';
import * as invoiceApi from '../functions/api/invoice/[[id]].js';

const F = JSON.parse(fs.readFileSync(new URL('./fixtures/tron_usdt_mainnet_tx.json', import.meta.url), 'utf8'));
const t = F.tronscan_transfers.token_transfers[0];
// fixture самосогласован: TronGrid и Tronscan видят один и тот же перевод
assert.strictEqual(F.trongrid_trc20.transaction_id, t.transaction_id);
assert.strictEqual(F.trongrid_trc20.value, t.quant);
assert.strictEqual(F.trongrid_trc20.to, t.to_address);
assert.strictEqual(F.trongrid_txinfo.receipt.result, 'SUCCESS');
assert.strictEqual(F.trongrid_trc20.token_info.address, PAIRS['USDT-TRC20'].token, 'mainnet USDT contract');

const m = new Map();
const env = { KV: { get: async (k) => m.get(k) ?? null, put: async (k, v) => { m.set(k, v); } } };
await env.KV.put(CONFIG_KEY, JSON.stringify({ addresses: { tron: t.to_address }, pairs: { 'USDT-TRC20': true } }));

const req = (body) => new Request('http://x', { method: 'POST', body: JSON.stringify(body) });
const mk = async () => (await (await invoiceCreate.onRequestPost({ env, request: req({ amount: 500 }) })).json()).id;
// create.js добавляет случайный хвост; для replay подгоняем сумму и время счёта под реальный перевод
const pin = async (id, dueMicro) => {
  const inv = JSON.parse(m.get('invoice:' + id));
  Object.assign(inv, { dueMicro: String(dueMicro), createdMs: t.block_ts - 30_000 });
  m.set('invoice:' + id, JSON.stringify(inv));
  await invoiceApi.onRequestPost({ env, params: { id }, request: req({ pair: 'USDT-TRC20' }) });
};
const status = async (id) => (await invoiceApi.onRequestPut({ env, params: { id } })).json();

const realFetch = globalThis.fetch;
const urls = [];
globalThis.fetch = async (u) => { urls.push(String(u)); return new Response(JSON.stringify(F.tronscan_transfers)); };
try {
  const miss = await mk(); await pin(miss, BigInt(t.quant) + 1n);
  assert.strictEqual((await status(miss)).status, 'pending', 'сумма на 1 микроюнит больше — не оплачено');

  const hit = await mk(); await pin(hit, t.quant);
  const r = await status(hit);
  assert.strictEqual(r.status, 'paid', JSON.stringify(r));
  assert.strictEqual(r.tx, t.transaction_id);
  assert.strictEqual(r.amount, Number(t.quant) / 1e6);
  assert.strictEqual(JSON.parse(m.get('invoice:' + hit)).status, 'paid');
  assert.strictEqual(m.get('paidtx:tron:' + t.transaction_id), hit);
  assert.ok(urls.every((u) => u.includes('relatedAddress=' + t.to_address)), 'запрос по адресу счёта');
} finally { globalThis.fetch = realFetch; }

console.log('tron replay: OK', t.transaction_id);
