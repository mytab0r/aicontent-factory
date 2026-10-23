/**
 * E2E приёма USDT-TRC20 на Nile (без затрат владельца; опционально — полный контур pay.pxbt.app).
 *
 * Сценарий (инвариант приёма): создать счёт -> перевести ровно dueMicro тестовых USDT мерчанту ->
 * найти оплату РЕАЛЬНЫМ матчером findPayments (прод-код paycheck.js) с Nile-контрактом/хостом через
 * env -> семантика paid: {tx, amount}.
 *
 * Запуск: NILE_E2E=1 node pay-pxbt/test/e2e/nile_e2e.mjs
 * Env: PAYER_PRIV, MERCHANT, NILE_USDT_CONTRACT (TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf — env, не хардкод),
 *      NILE_TRONSCAN (по умолчанию https://nileapi.tronscan.org).
 * CI: без NILE_E2E=1 — skip.
 */
import assert from 'node:assert';
import crypto from 'node:crypto';

const e = process.env;
if (e.NILE_E2E !== '1') { console.log('nile e2e: skipped (set NILE_E2E=1)'); process.exit(0); }
const need = (k) => { const v = e[k]; if (!v) { console.error(`nile e2e: missing env ${k}`); process.exit(2); } return v; };

const PAYER_PRIV = need('PAYER_PRIV');
const MERCHANT = need('MERCHANT');
const USDT = need('NILE_USDT_CONTRACT');
const here = new URL('.', import.meta.url).pathname;
const { toMicro, findPayments } = await import(here + '../../functions/lib/paycheck.js');

// env-мост для прод-модулей (см. pairToken/TRONSCAN_BASE в lib)
globalThis.PAY_PAIR_TOKEN_ENV = (pairId) => (pairId === 'USDT-TRC20' ? USDT : undefined);
globalThis.TRONSCAN_BASE_ENV = () => e.NILE_TRONSCAN || 'https://nileapi.tronscan.org';

// --- base58check без зависимостей
const ALPH = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function b58dec(str) {
  let x = 0n;
  for (const c of str) x = x * 58n + BigInt(ALPH.indexOf(c));
  return x.toString(16).padStart(50, '0').slice(0, 42);
}
const post = async (path, body) => {
  const r = await fetch('https://nile.trongrid.io' + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(path + ' -> ' + r.status + ' ' + (await r.text()).slice(0, 200));
  return r.json();
};

// --- ключ -> адрес (ed25519 seed из приватника)
const p8 = Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), Buffer.from(PAYER_PRIV, 'hex')]);
const key = crypto.createPrivateKey({ key: p8, format: 'der', type: 'pkcs8' });
const pubRaw = crypto.createPublicKey(key).export({ type: 'spki', format: 'der' }).subarray(12);
const kh = crypto.createHash('sha3-256').update(pubRaw).digest();
const payload = Buffer.concat([Buffer.from([0x41]), kh.subarray(12)]);
const ch = crypto.createHash('sha256').update(crypto.createHash('sha256').update(payload).digest()).digest();
const hexToB58 = (buf) => { let x = BigInt('0x' + buf.toString('hex')), s = ''; while (x > 0n) { s = ALPH[Number(x % 58n)] + s; x /= 58n; } for (const b of buf) { if (b === 0) s = '1' + s; else break; } return s; };
const PAYER = hexToB58(Buffer.concat([payload, ch.subarray(0, 4)]));
console.log('payer:', PAYER);

// --- preflight: TRX и USDT у плательщика
const acct = await post('/wallet/getaccount', { address: PAYER, visible: true });
const trxBalance = acct.balance || 0;
if (trxBalance <= 5_000_000) {
  console.error(`nile e2e: у плательщика ${trxBalance / 1e6} TRX — нужен faucet (nileex.io, капча: человек) или TronFAQBot !nile ${PAYER}`);
  process.exit(3);
}

// --- 1) счёт: уникальная сумма как в create.js (база 1 USD-цент... хвост 1..999 микроюнитов)
const tail = 1 + (crypto.getRandomValues(new Uint16Array(1))[0] % 999);
const dueMicro = BigInt(10_000 + tail); // 0.01 USD-экв + хвост — тестовые токены, не деньги владельца
const createdMs = Date.now();
console.log('invoice(local): dueMicro =', dueMicro.toString());

// --- 2) перевод ровно dueMicro USDT мерчанту
const param = 'a9059cbb' + '0'.repeat(24) + b58dec(MERCHANT).slice(2) + dueMicro.toString(16).padStart(64, '0');
const tx = await post('/wallet/triggersmartcontract', {
  owner_address: PAYER, contract_address: USDT, function_selector: 'transfer(address,uint256)',
  parameter: param, fee_limit: 100_000_000, call_value: 0, visible: true,
});
assert.ok(tx.transaction && tx.result?.result !== false, 'trigger: ' + JSON.stringify(tx).slice(0, 300));
const raw = tx.transaction;
raw.signature = [crypto.sign(null, Buffer.from(raw.raw_data_hex, 'hex'), key).toString('hex')];
const bcast = await post('/wallet/broadcasttransaction', raw);
assert.strictEqual(bcast.result, true, 'broadcast: ' + JSON.stringify(bcast));
console.log('nile tx:', bcast.txid);

// --- 3) реальный матчер до совпадения (paid)
const pair = { chain: 'tron', asset: 'USDT', token: USDT, decimals: 6, address: MERCHANT };
let hit = null;
for (let i = 0; i < 36 && !hit; i++) {
  await new Promise((r) => setTimeout(r, 5000));
  const ms = await findPayments(pair, MERCHANT, dueMicro, createdMs);
  hit = ms[0] || null;
  if (i % 6 === 0) console.log('matcher poll', i, hit ? 'HIT' : 'pending');
}
assert.ok(hit, 'матчер не нашёл перевод');
assert.strictEqual(hit.tx, bcast.txid);
console.log('COMPONENT OK:', JSON.stringify({ tx: hit.tx, amount: hit.amount, status: 'paid' }));

console.log('E2E OK');
console.log(JSON.stringify({ tx: bcast.txid, amount: Number(dueMicro) / 1e6, status: 'paid' }));
