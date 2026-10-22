/**
 * E2E на Tron Nile: реальный server.mjs (makeServer) -> счёт -> перевод тестовых USDT -> статус paid.
 * Без денег владельца: только Nile testnet. Env:
 *   TRON_API=https://nile.trongrid.io  TRON_USDT_CONTRACT=TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf
 *   NILE_PAYER_KEY=<hex priv с тестовыми USDT+TRX>  NILE_MERCHANT=<T-адрес получателя>
 *   E2E_OUT=<путь для JSON-артефакта> (опц.)
 * Запуск: node scripts/e2e_nile.mjs
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { trc20Transfer, addressOf } from './tron_nile.mjs';

const E = process.env;
for (const k of ['TRON_API', 'TRON_USDT_CONTRACT', 'NILE_PAYER_KEY', 'NILE_MERCHANT']) if (!E[k]) throw new Error('env ' + k + ' required');
if (!/nile|shasta/.test(E.TRON_API) || E.TRON_USDT_CONTRACT === 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t') throw new Error('only testnet');

const { makeServer } = await import('../deploy/pay-page/server.mjs');
const { CONFIG_KEY, PAIRS } = await import('../functions/lib/config.js');
if (PAIRS['USDT-TRC20'].token !== E.TRON_USDT_CONTRACT) throw new Error('TRON_USDT_CONTRACT не применился');

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pay-e2e-'));
fs.writeFileSync(path.join(dataDir, 'kv.json'), JSON.stringify({ [CONFIG_KEY]: { v: JSON.stringify({ addresses: { tron: E.NILE_MERCHANT }, pairs: { 'USDT-TRC20': true } }) } }));
const token = 'e2e-' + Math.random().toString(36).slice(2);
const srv = makeServer({ dataDir, apiToken: token });
await new Promise((r) => srv.listen(0, 'localhost', r));
const base = 'http://' + 'localhost:' + srv.address().port;
const call = async (m, p, body, h = {}) => {
  const r = await fetch(base + p, { method: m, headers: { 'content-type': 'application/json', ...h }, body: body && JSON.stringify(body) });
  return { status: r.status, json: await r.json() };
};

try {
  const c = await call('POST', '/api/invoice', { amount: 1, memo: 'nile e2e' }, { authorization: 'Bearer ' + token });
  if (c.status !== 200) throw new Error('create ' + JSON.stringify(c));
  const id = c.json.id;
  const sel = await call('POST', '/api/invoice/' + id, { pair: 'USDT-TRC20' });
  if (!sel.json.ok) throw new Error('pair ' + JSON.stringify(sel));
  const inv = JSON.parse(JSON.parse(fs.readFileSync(path.join(dataDir, 'kv.json'), 'utf8'))['invoice:' + id].v);
  console.log('invoice', id, 'due', inv.amount, 'to', E.NILE_MERCHANT);
  const pend = await call('PUT', '/api/invoice/' + id);
  if (pend.json.status !== 'pending') throw new Error('expected pending before payment: ' + JSON.stringify(pend));

  const tx = await trc20Transfer({ api: E.TRON_API, privHex: E.NILE_PAYER_KEY, contract: E.TRON_USDT_CONTRACT, to: E.NILE_MERCHANT, amountRaw: inv.dueMicro });
  console.log('sent tx', tx, 'from', addressOf(E.NILE_PAYER_KEY));

  let st;
  for (let i = 0; i < 40; i++) { // ~3 мин: подтверждение на TronGrid (solidified) ~1 мин
    await new Promise((r) => setTimeout(r, 5000));
    st = await call('PUT', '/api/invoice/' + id);
    if (st.json.status === 'paid') break;
  }
  if (st.json.status !== 'paid' || st.json.tx !== tx) throw new Error('not paid: ' + JSON.stringify(st));
  srv.reloadKV();
  const final = JSON.parse(JSON.parse(fs.readFileSync(path.join(dataDir, 'kv.json'), 'utf8'))['invoice:' + id].v);
  const out = { network: 'tron-nile', api: E.TRON_API, usdt_contract: E.TRON_USDT_CONTRACT, invoice_id: id, tx_hash: tx,
    explorer: 'https://nile.tronscan.org/#/transaction/' + tx, status_response: st.json, invoice: final, at: new Date().toISOString() };
  if (E.E2E_OUT) fs.writeFileSync(E.E2E_OUT, JSON.stringify(out, null, 1) + '\n');
  console.log(JSON.stringify(out, null, 1));
} finally {
  srv.close();
}
