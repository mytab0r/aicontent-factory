/**
 * Верификация подписей владелецем (proof-of-ownership адресов). Без внешних пакетов:
 * vendored @noble/{secp256k1,ed25519,hashes} (см. vendor/noble, MIT).
 *
 * Сообщение, которое подписывает владелец, формирует /api/claim/nonce — формат:
 *   pay.pxbt.app: claim <nonce>\nвладелец pxbt.app
 * Проверяемая подпись подтверждает владение приватным ключом адреса.
 */
import { sha256, sha512 } from '../vendor/noble/hashes/sha2.js';
import { keccak_256 } from '../vendor/noble/hashes/sha3.js';
import * as secp from '../vendor/noble/secp256k1/secp256k1.js';
import * as ed from '../vendor/noble/ed25519/ed25519.js';
import { verifyBtcSignedMessage } from '../vendor/btc-verify.js';
import { verifyTonProof } from '../vendor/ton-wallet.js';

// noble-secp256k1/ed25519 3.x требуют явных синхронных хэш-провайдеров
secp.hashes.sha256 = sha256;
ed.hashes.sha512 = sha512;

export const TON_PROOF_DOMAIN = 'pay.pxbt.app';

const enc = new TextEncoder();

function bytesToHex(b) {
  let s = '';
  for (const x of b) s += x.toString(16).padStart(2, '0');
  return s;
}
function hexToBytes(hex) {
  const h = hex.startsWith('0x') ? hex.slice(2) : hex;
  const out = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.slice(i * 2, i * 2 + 2), 16);
  return out;
}

const B58_ALPH = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function base58Encode(bytes) {
  let n = 0n;
  for (const b of bytes) n = n * 256n + BigInt(b);
  let s = '';
  while (n > 0n) {
    s = B58_ALPH[Number(n % 58n)] + s;
    n /= 58n;
  }
  for (const b of bytes) {
    if (b === 0) s = '1' + s;
    else break;
  }
  return s;
}
function base58Decode(s) {
  let n = 0n;
  for (const c of s) {
    const i = B58_ALPH.indexOf(c);
    if (i < 0) throw new Error('bad base58 char');
    n = n * 58n + BigInt(i);
  }
  const bytes = [];
  while (n > 0n) {
    bytes.unshift(Number(n % 256n));
    n /= 256n;
  }
  let zeros = 0;
  for (const c of s) {
    if (c === '1') zeros++;
    else break;
  }
  return new Uint8Array([...Array(zeros).fill(0), ...bytes]);
}

function eip191Digest(msg) {
  const m = enc.encode(msg);
  return keccak_256(
    new Uint8Array([...enc.encode('\x19Ethereum Signed Message:\n' + m.length), ...m])
  );
}
// TronWeb signMessageV2: \x19TRON Signed Message:\n<len><msg>, затем keccak
function tronDigest(msg) {
  const m = enc.encode(msg);
  return keccak_256(
    new Uint8Array([...enc.encode('\x19TRON Signed Message:\n' + m.length), ...m])
  );
}

/** EVM: personal_sign (65 байт: r||s||v, v ∈ {27,28} или {0,1}). Адрес восстанавливается из подписи. */
function verifyEvm(msg, sig, expectedAddress) {
  const recovered = evmRecover(msg, sig);
  if (!expectedAddress) throw new Error('evm requires address');
  if (normalizeAddress('evm', recovered) !== normalizeAddress('evm', expectedAddress)) {
    throw new Error('signature does not match address');
  }
  return { address: normalizeAddress('evm', expectedAddress), chainKind: 'evm' };
}

function evmRecover(msg, sig) {
  let h = sig.startsWith('0x') ? sig.slice(2) : sig;
  if (h.length !== 130) throw new Error('evm sig must be 65 bytes');
  const r = h.slice(0, 64);
  const s = h.slice(64, 128);
  let v = parseInt(h.slice(128, 130), 16);
  let recId = v >= 27 ? v - 27 : v;
  if (recId < 0 || recId > 3) throw new Error('bad v');
  const rec = new Uint8Array(65);
  rec[0] = recId;
  rec.set(hexToBytes(r + s), 1);
  const pub = secp.recoverPublicKey(rec, eip191Digest(msg), { prehash: false, isCompressed: false });
  return '0x' + bytesToHex(keccak_256(pub.slice(1)).slice(12));
}

/** Tron: signMessageV2 — r||s||v как в EVM (v=27/28), префикс \x19TRON Signed Message:\n. */
function verifyTron(msg, sig, expectedAddress) {
  const raw = hexToBytes(sig);
  if (raw.length !== 65) throw new Error('tron sig must be 65 bytes');
  let v = raw[64];
  if (v >= 27) v -= 27;
  if (v < 0 || v > 3) throw new Error('bad tron recovery byte');
  const rec = new Uint8Array(65);
  rec[0] = v;
  rec.set(raw.slice(0, 64), 1);
  const pub = secp.recoverPublicKey(rec, tronDigest(msg), { prehash: false, isCompressed: false });
  const payload = new Uint8Array(21);
  payload[0] = 0x41;
  payload.set(keccak_256(pub.slice(1)).slice(12), 1);
  // base58check: 4 байта sha256(sha256(payload)) в хвост
  const d1 = sha256(payload);
  const d2 = sha256(new Uint8Array(d1));
  const full = new Uint8Array(25);
  full.set(payload, 0);
  full.set(d2.slice(0, 4), 21);
  const recovered = base58Encode(full);
  if (!expectedAddress) throw new Error('tron requires address');
  if (recovered !== expectedAddress) throw new Error('signature does not match address');
  return { address: expectedAddress, chainKind: 'tron' };
}

/** Solana: ed25519 detached, адрес = base58(pubkey 32b). */
function verifySolana(msg, sigB64, expectedAddress) {
  const sig = Uint8Array.from(atob(sigB64), (c) => c.charCodeAt(0));
  const pub = base58Decode(expectedAddress);
  if (pub.length !== 32) throw new Error('solana addr must be 32-byte base58');
  if (!ed.verify(sig, enc.encode(msg), pub)) throw new Error('bad solana signature');
  return { address: expectedAddress, chainKind: 'solana' };
}

/** BTC: BIP-137 signed message, P2WPKH (bc1q) only. Адрес = HASH160(recovered pubkey) -> bech32. */
function verifyBtc(msg, sigB64, expectedAddress) {
  if (!expectedAddress) throw new Error('btc requires address');
  verifyBtcSignedMessage({ message: msg, signatureBase64: sigB64, claimedAddress: expectedAddress });
  return { address: expectedAddress, chainKind: 'btc' };
}

/**
 * TON: TON Connect ton_proof. `signature` здесь — JSON-строка {address, stateInit, proof}
 * (TonConnect TonAddressItemReply), не сырая подпись — proof содержит её в base64 внутри.
 * Публичный ключ НЕ берётся у клиента: извлекается из data-cell распарсенного stateInit,
 * адрес проверяется как sha256(stateInit) == заявленный адрес.
 */
function verifyTon(nonceMessage, signaturePayload) {
  let parsed;
  try {
    parsed = typeof signaturePayload === 'string' ? JSON.parse(signaturePayload) : signaturePayload;
  } catch {
    throw new Error('ton signature must be JSON {address, stateInit, proof}');
  }
  const { address, stateInit, proof } = parsed || {};
  if (!proof || typeof proof.payload !== 'string') throw new Error('missing ton proof');
  // payload привязывает proof к конкретному nonce — тому же, что выдал /api/claim/nonce.
  if (proof.payload !== nonceMessage) throw new Error('ton proof payload does not match issued nonce');
  const friendlyAddress = verifyTonProof({ address, stateInit, proof }, { domain: TON_PROOF_DOMAIN });
  return { address: friendlyAddress, chainKind: 'ton' };
}

/**
 * Проверить подпись. chain: 'evm' | 'tron' | 'solana' | 'btc' | 'ton'.
 * EVM/Tron/BTC: адрес восстанавливается из подписи (подделать нельзя).
 * Solana: подпись проверяется против заявленного адреса (pubkey = адрес).
 * TON: ton_proof верифицируется против публичного ключа, извлечённого из stateInit.
 * Возвращает {address, chainKind} или кидает исключение.
 */
export function verifyWalletSignature({ chain, message, signature, address }) {
  if (chain === 'ton') return verifyTon(message, signature);
  if (!message || typeof message !== 'string' || message.length > 512) {
    throw new Error('bad message');
  }
  if (!message.startsWith('pay.pxbt.app: claim ')) {
    throw new Error('message must be a fresh claim nonce from this server');
  }
  if (chain === 'evm') return verifyEvm(message, signature, address);
  if (chain === 'tron') return verifyTron(message, signature, address);
  if (chain === 'btc') return verifyBtc(message, signature, address);
  if (chain === 'solana') {
    if (!address) throw new Error('solana requires address');
    return verifySolana(message, signature, address);
  }
  throw new Error('unknown chain: ' + chain);
}

/** Нормализация адреса для хранения/сравнения (без EIP-55 checksum). */
export function normalizeAddress(chain, address) {
  if (chain === 'evm') return address.toLowerCase();
  return address; // tron/solana/btc/ton — чувствительны к регистру, храним как есть
}
