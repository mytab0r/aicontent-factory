/**
 * E2E Tron Nile testnet (pay.pxbt.app, USDT-TRC20): счёт -> перевод -> paid.
 *
 * Запуск: NILE_E2E=1 node pay-pxbt/test/e2e/nile_e2e.mjs
 * Env:
 *   NILE_E2E=1            — включить (иначе skip, CI-безопасно)
 *   PAYER_PRIV            — приватный ключ плательщика (/opt/data/secrets/tron-nile-e2e.json)
 *   MERCHANT              — base58 адрес мерчанта (адрес приёма из конфига pay)
 *   NILE_USDT_CONTRACT    — адрес USDT Nile (TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf) — env, не mainnet-хардкод
 *   NILE_RPC              — RPC Nile (по умолчанию RPC_NILE_HOST в коде ниже)
 *   PAY_BASE / PAY_API_TOKEN — инстанс pay для /api/invoice
 *
 * Сценарий: создать счёт (уникальная сумма с хвостом), перевести ровно dueMicro USDT
 * мерчанту, поллить /status до paid. Preflight проверяет TRX/USDT и подсказывает faucet.
 */
import assert from 'node:assert';
import crypto from 'node:crypto';

const e = process.env;
if (e.NILE_E2E !== '1') { console.log('nile e2e: skipped (set NILE_E2E=1)'); process.exit(0); }
const need = (k) => { const v = e[k]; if (!v) { console.error(`nile e2e: missing env ${k}`); process.exit(2); } return v; };

const PAYER_PRIV = need('PAYER_PRIV');
const MERCHANT = need('MERCHANT');
const USDT = need('NILE_USDT_CONTRACT');
const RPC = e.NILE_RPC || 'RPC_NILE_HOST';
const PAY_BASE = e.PAY_BASE || 'PAY_BASE_HOST';
const PAY_TOKEN = e.PAY_API_TOKEN || '';

// --- base58check (адреса) без зависимостей
const ALPH = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function b58enc(buf) {
  let x = BigInt('0x' + buf.toString('hex')), s = '';
  while (x > 0n) { s = ALPH[Number(x % 58n)] + s; x /= 58n; }
  for (const b of buf) { if (b === 0) s = '1' + s; else break; }
  return s;
}
function b58dec(str) {
  let x = 0n;
  for (const c of str) x = x * 58n + BigInt(ALPH.indexOf(c));
  return x.toString(16).padStart(50, '0').slice(0, 42); // 41 + 20 байт
}

const post = async (path, body) => {
  const r = await fetch(RPC + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(path + ' -> ' + r.status + ' ' + (await r.text()).slice(0, 200));
  return r.json();
};

// --- ключ -> адрес (ed25519 seed из приватника)
const p8 = Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), Buffer.from(PAYER_PRIV, 'hex')]);
const key = crypto.createPrivateKey({ key: p8, format: 'der', type: 'pkcs8' });
const pubRaw = crypto.createPublicKey(key).export({ type: 'spki', format: 'der' }).subarray(12);
const kh = crypto.createHash('sha3-256').update(pubRaw).digest(); // keccak256
const payload = Buffer.concat([Buffer.from([0x41]), kh.subarray(12)]);
const ch = crypto.createHash('sha256').update(crypto.createHash('sha256').update(payload).digest()).digest();
const PAYER = b58enc(Buffer.concat([payload, ch.subarray(0, 4)]));
console.log('payer:', PAYER);

// --- preflight: TRX (bandwidth/energy) у плательщика
const acct = await post('/wallet/getaccount', { address: PAYER, visible: true });
const trxBalance = acct.balance || 0;
if (trxBalance <= 5_000_000) {
  console.error(`nile e2e: у плательщика ${trxBalance / 1e6} TRX — пополни (nileex.io faucet или TronFAQBot: !nile ${PAYER}, !nile_usdt ${PAYER})`);
  process.exit(3);
}

// --- 1) счёт
const inv = await (await fetch(PAY_BASE + '/api/invoice', {
  method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer ' + PAY_TOKEN },
  body: JSON.stringify({ amount: 1 }),
})).json();
assert.ok(inv.id, 'invoice create: ' + JSON.stringify(inv));
const invFull = await (await fetch(`${PAY_BASE}/api/invoice/${inv.id}`)).json();
const dueMicro = BigInt(invFull.dueMicro);
console.log('invoice:', inv.id, 'dueMicro:', dueMicro);

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

// --- 3) полл статуса до paid (до 3 минут)
let st = { status: '' };
for (let i = 0; i < 36 && st.status !== 'paid'; i++) {
  await new Promise((r) => setTimeout(r, 5000));
  st = await (await fetch(`${PAY_BASE}/api/invoice/${inv.id}/status`, { method: 'PUT' })).json();
  if (i % 6 === 0) console.log('poll', i, st.status, st.tx || '');
}
assert.strictEqual(st.status, 'paid', 'не paid: ' + JSON.stringify(st));
console.log('E2E OK: invoice', inv.id, 'paid by tx', st.tx);
console.log(JSON.stringify({ invoice: inv.id, tx: st.tx, status: 'paid' }));
