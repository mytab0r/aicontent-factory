/**
 * E2E приёма USDT-TRC20 на Nile (без затрат владельца).
 *
 * Сценарий (инвариант приёма): локальный счёт с уникальной суммой (хвост, как в create.js) ->
 * перевести ровно dueMicro тестовых USDT мерчанту (secp256k1-подпись TRON) ->
 * найти оплату РЕАЛЬНЫМ матчером findPayments (прод-код paycheck.js) через
 * nileapi.tronscan.org -> семантика paid: {tx, amount}.
 *
 * Запуск: NILE_E2E=1 node pay-pxbt/test/e2e/nile_e2e.mjs
 * Env: PAYER_PRIV (64 hex, secp256k1), MERCHANT, NILE_USDT_CONTRACT (TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf —
 *      env, не mainnet-хардкод), NILE_TRONSCAN (по умолчанию https://nileapi.tronscan.org).
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
// база tronscan читается при импорте модуля — переопределение обязано быть ДО него
globalThis.TRONSCAN_BASE_ENV = () => e.NILE_TRONSCAN || 'https://nileapi.tronscan.org';
const { findPayments } = await import(new URL('../../../functions/lib/paycheck.js', import.meta.url).href);

// --- keccak256 (fIPS-независимый, padding 0x01) — без зависимостей
function keccak256(data) {
  const RC = [0x0000000000000001n,0x0000000000008082n,0x800000000000808An,0x8000000080008000n,
    0x000000000000808Bn,0x0000000080000001n,0x8000000080008081n,0x8000000000008009n,
    0x000000000000008An,0x0000000000000088n,0x0000000080008009n,0x000000008000000An,
    0x000000008000808Bn,0x800000000000008Bn,0x8000000000008089n,0x8000000000008003n,
    0x8000000000008002n,0x8000000000000080n,0x000000000000800An,0x800000008000000An,
    0x8000000080008081n,0x8000000000008080n,0x0000000080000001n,0x8000000080008008n];
  const ROT = [[0,36,3,41,18],[1,44,10,45,2],[62,6,43,15,61],[28,55,25,21,56],[27,20,39,8,14]];
  const M = (1n << 64n) - 1n;
  const rol = (x, n) => (n ? ((x << BigInt(n)) | (x >> BigInt(64 - n))) & M : x);
  const f = (A) => {
    for (let rnd = 0; rnd < 24; rnd++) {
      const C = [0,1,2,3,4].map((x) => A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4]);
      const D = [0,1,2,3,4].map((x) => C[(x + 4) % 5] ^ rol(C[(x + 1) % 5], 1));
      for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) A[x][y] ^= D[x];
      const B = [[0n,0n,0n,0n,0n],[0n,0n,0n,0n,0n],[0n,0n,0n,0n,0n],[0n,0n,0n,0n,0n],[0n,0n,0n,0n,0n]];
      for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) B[y][(2 * x + 3 * y) % 5] = rol(A[x][y], ROT[x][y]);
      for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) A[x][y] = B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y] & M);
      A[0][0] ^= RC[rnd];
    }
  };
  const rate = 136;
  const padded = Buffer.from(data);
  const buf = Buffer.concat([padded, Buffer.from([0x01])]);
  const full = Buffer.alloc(Math.ceil((buf.length + 1) / rate) * rate);
  buf.copy(full); full[buf.length - 1] ^= 0x80; full[buf.length - 1] |= 0x80;
  // Упростим: стандартный pad10*1 c 0x01: append 0x01, нули, последний байт |= 0x80
  const paddedBuf = Buffer.alloc(Math.ceil((padded.length + 1) / rate) * rate);
  padded.copy(paddedBuf); paddedBuf[padded.length] = 0x01; paddedBuf[paddedBuf.length - 1] |= 0x80;
  const A = Array.from({ length: 5 }, () => [0n, 0n, 0n, 0n, 0n]);
  for (let off = 0; off < paddedBuf.length; off += rate) {
    for (let i = 0; i < rate / 8; i++) A[i % 5][(i / 5) | 0] ^= paddedBuf.readBigUInt64LE(off + i * 8);
    f(A);
  }
  const out = Buffer.alloc(32);
  for (let i = 0; i < 4; i++) out.writeBigUInt64LE(A[i % 5][(i / 5) | 0], i * 8);
  return out;
}

// --- secp256k1 (pubkey derive + ECDSA sign RFC6979) — без зависимостей
const P = (1n << 256n) - 0x1000003d1n;
const N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141n;
const Gx = 0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798n;
const Gy = 0x483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8n;
const G = [Gx, Gy];
const mod = (a, m = P) => ((a % m) + m) % m;
function powmod(b, e, m) { let r = 1n; b %= m; while (e) { if (e & 1n) r = r * b % m; b = b * b % m; e >>= 1n; } return r; }
const invm = (a, m = P) => powmod(mod(a, m), m - 2n, m);
const padd = (A, B) => {
  if (!A) return B; if (!B) return A;
  const [x1, y1] = A, [x2, y2] = B;
  if (x1 === x2 && mod(y1 + y2) === 0n) return null;
  const dbl = x1 === x2 && y1 === y2; // одна точка (по значению), не по ссылке
  const lam = dbl ? mod(3n * x1 * x1 * invm(2n * y1)) : mod(mod(y2 - y1) * invm(mod(x2 - x1)));
  const x3 = mod(lam * lam - x1 - x2);
  return [x3, mod(lam * (x1 - x3) - y1)];
};
const pmul = (k, pt) => { let r = null; while (k) { if (k & 1n) r = padd(r, pt); pt = padd(pt, pt); k >>= 1n; } return r; };

function rfc6979K(priv, msgHash) {
  // deterministic k (RFC6979, HMAC-SHA256)
  let V = Buffer.alloc(32, 1), K = Buffer.alloc(32, 0);
  const x = Buffer.from(priv.replace(/^0x/, '').padStart(64, '0'), 'hex');
  const h1 = msgHash;
  K = crypto.createHmac('sha256', K).update(Buffer.concat([V, Buffer.from([0]), x, h1])).digest();
  V = crypto.createHmac('sha256', K).update(V).digest();
  K = crypto.createHmac('sha256', K).update(Buffer.concat([V, Buffer.from([1]), x, h1])).digest();
  V = crypto.createHmac('sha256', K).update(V).digest();
  for (;;) {
    V = crypto.createHmac('sha256', K).update(V).digest();
    const k = BigInt('0x' + V.toString('hex'));
    if (k >= 1n && k < N) return k;
    K = crypto.createHmac('sha256', K).update(Buffer.concat([V, Buffer.from([0])])).digest();
    V = crypto.createHmac('sha256', K).update(V).digest();
  }
}
function ecdsaSign(privBig, msgHash) {
  const z = BigInt('0x' + msgHash.toString('hex'));
  for (;;) {
    const k = rfc6979K(privBig.toString(16).padStart(64, '0'), msgHash);
    const R = pmul(k, G);
    const r = mod(R[0], N);
    if (r === 0n) { continue; }
    const s = mod(invm(k, N) * (z + r * privBig) % N, N);
    if (s === 0n) { continue; }
    const half = s > N / 2n;
    return { r, s: half ? N - s : s, rec: ((R[1] & 1n) | (R[0] >= N ? 2n : 0n)) ^ (half ? 1n : 0n) };
  }
}

// --- base58check
const ALPH = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function b58(buf) {
  let x = BigInt('0x' + buf.toString('hex')), s = '';
  while (x > 0n) { s = ALPH[Number(x % 58n)] + s; x /= 58n; }
  for (const b of buf) { if (b === 0) s = '1' + s; else break; }
  return s;
}
function b58dec(str) {
  let x = 0n;
  for (const c of str) { const i = ALPH.indexOf(c); if (i < 0) throw new Error('bad base58'); x = x * 58n + BigInt(i); }
  return Buffer.from(x.toString(16).padStart(50, '0'), 'hex');
}

// --- ключ -> TRON адрес (secp256k1 + keccak)
const privBig = BigInt('0x' + PAYER_PRIV);
assert.ok(privBig > 0n && privBig < N, 'bad priv');
const pub = pmul(privBig, G);
const pubBytes = Buffer.concat([pub[0].toString(16).padStart(64, '0'), pub[1].toString(16).padStart(64, '0')].map((s) => Buffer.from(s, 'hex')));
const addrBytes = Buffer.concat([Buffer.from([0x41]), keccak256(pubBytes).subarray(12)]);
const PAYER = b58(Buffer.concat([addrBytes, crypto.createHash('sha256').update(crypto.createHash('sha256').update(addrBytes).digest()).digest().subarray(0, 4)]));
console.log('payer:', PAYER);
const merchantBytes = b58dec(MERCHANT);
assert.strictEqual(merchantBytes.length, 25, 'bad MERCHANT');
assert.strictEqual(merchantBytes[0], 0x41, 'bad MERCHANT prefix');

const post = async (path, body) => {
  const r = await fetch('https://nile.trongrid.io' + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(path + ' -> ' + r.status + ' ' + (await r.text()).slice(0, 200));
  return r.json();
};

// --- preflight: TRX у плательщика (bandwidth/energy)
const acct = await post('/wallet/getaccount', { address: PAYER, visible: true });
const trxBalance = acct.balance || 0;
if (trxBalance <= 5_000_000) {
  console.error(`nile e2e: у плательщика ${PAYER} ${trxBalance / 1e6} TRX — нужен faucet (nileex.io, капча: только человек) или TronFAQBot !nile ${PAYER} / !nile_usdt ${PAYER}`);
  process.exit(3);
}

// --- 1) счёт: уникальная сумма как в create.js (хвост 1..999 микроюнитов)
const tail = 1n + BigInt(crypto.getRandomValues(new Uint16Array(1))[0] % 999);
const dueMicro = 10_000n + tail;
const createdMs = Date.now();
console.log('invoice(local): dueMicro =', dueMicro.toString());

// --- 2) перевод ровно dueMicro USDT мерчанту
// селектор a9059cbb узел добавляет сам — в parameter только аргументы
const param = '0'.repeat(24) + merchantBytes.subarray(1, 21).toString('hex') + dueMicro.toString(16).padStart(64, '0');
const tx = await post('/wallet/triggersmartcontract', {
  owner_address: PAYER, contract_address: USDT, function_selector: 'transfer(address,uint256)',
  parameter: param, fee_limit: 100_000_000, call_value: 0, visible: true,
});
assert.ok(tx.transaction && tx.result?.result !== false, 'trigger: ' + JSON.stringify(tx).slice(0, 300));
const raw = tx.transaction;
const hash = crypto.createHash('sha256').update(Buffer.from(raw.raw_data_hex, 'hex')).digest(); // TRON: txID = sha256(raw_data)
const { r, s, rec } = ecdsaSign(privBig, hash);
const hx = (n) => n.toString(16).padStart(64, '0');
const mk = (v) => Buffer.from(hx(r) + hx(s) + v.toString(16).padStart(2, '0'), 'hex').toString('hex');
let bcast = null;
for (const v of [Number(rec & 1n), Number(rec & 1n) ^ 1]) {
  raw.signature = [mk(v)];
  bcast = await post('/wallet/broadcasttransaction', raw);
  if (bcast.result === true) break;
}
assert.strictEqual(bcast.result, true, 'broadcast: ' + JSON.stringify(bcast));
console.log('nile tx:', bcast.txid);

// --- 3) реальный матчер до совпадения (paid)
const pair = { chain: 'tron', asset: 'USDT', token: USDT, decimals: 6, address: MERCHANT };
let hit = null;
for (let i = 0; i < 36 && !hit; i++) {
  await new Promise((res) => setTimeout(res, 5000));
  const ms = await findPayments(pair, MERCHANT, dueMicro, createdMs);
  hit = ms[0] || null;
  if (i % 6 === 0) console.log('matcher poll', i, hit ? 'HIT' : 'pending');
}
assert.ok(hit, 'матчер не нашёл перевод');
assert.strictEqual(hit.tx, bcast.txid);
console.log('E2E OK');
console.log(JSON.stringify({ tx: bcast.txid, amount: Number(dueMicro) / 1e6, status: 'paid' }));
