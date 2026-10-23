/**
 * Минимальный Tron-клиент на vendored noble (без npm): ключи, адрес, подпись и broadcast TRC20 transfer.
 * Только для E2E на testnet (Nile). Ключ — из env, в git не попадает.
 */
import { sha256 } from '../functions/vendor/noble/hashes/sha2.js';
import { keccak_256 } from '../functions/vendor/noble/hashes/sha3.js';
import * as secp from '../functions/vendor/noble/secp256k1/secp256k1.js';
import { hmac } from '../functions/vendor/noble/hashes/hmac.js';

secp.hashes.sha256 = sha256;
secp.hashes.hmacSha256 = (k, ...m) => hmac(sha256, k, secp.etc.concatBytes(...m));

const B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
const hex = (b) => Buffer.from(b).toString('hex');
const unhex = (h) => new Uint8Array(Buffer.from(h, 'hex'));

function b58check(payload) {
  const full = new Uint8Array([...payload, ...sha256(sha256(payload)).slice(0, 4)]);
  let n = BigInt('0x' + hex(full)), s = '';
  while (n > 0n) { s = B58[Number(n % 58n)] + s; n /= 58n; }
  for (const b of full) { if (b) break; s = '1' + s; }
  return s;
}
export function b58ToHex41(addr) {
  let n = 0n;
  for (const c of addr) n = n * 58n + BigInt(B58.indexOf(c));
  return n.toString(16).padStart(50, '0').slice(0, 42); // 41 + 20 байт, без checksum
}
export function addressOf(privHex) {
  const pub = secp.getPublicKey(unhex(privHex), false);
  return b58check(new Uint8Array([0x41, ...keccak_256(pub.slice(1)).slice(12)]));
}
export const newKey = () => hex(secp.utils.randomSecretKey());

async function post(api, path, body) {
  const r = await fetch(api + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(path + ' ' + r.status + ' ' + JSON.stringify(j));
  return j;
}

/** TRC20 transfer(to, amountRaw): triggersmartcontract -> подпись txID -> broadcast. Возврат txID. */
export async function trc20Transfer({ api, privHex, contract, to, amountRaw, feeLimit = 100_000_000 }) {
  const from = addressOf(privHex);
  const param = b58ToHex41(to).slice(2).padStart(64, '0') + BigInt(amountRaw).toString(16).padStart(64, '0');
  const t = await post(api, '/wallet/triggersmartcontract', {
    owner_address: from, contract_address: contract, function_selector: 'transfer(address,uint256)',
    parameter: param, fee_limit: feeLimit, call_value: 0, visible: true,
  });
  if (!t.result?.result) throw new Error('trigger failed: ' + JSON.stringify(t.result));
  const tx = t.transaction;
  const sig = secp.sign(unhex(tx.txID), unhex(privHex), { prehash: false, format: 'recovered' });
  // noble 3.x recovered = recovery(1) || r(32) || s(32); Tron ждёт r||s||v
  tx.signature = [hex(sig.slice(1)) + hex(sig.slice(0, 1))];
  const b = await post(api, '/wallet/broadcasttransaction', tx);
  if (!b.result) throw new Error('broadcast failed: ' + JSON.stringify(b));
  return tx.txID;
}
