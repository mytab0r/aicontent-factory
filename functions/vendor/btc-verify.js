/**
 * Bitcoin signed-message verification (BIP-137 header byte format) + P2WPKH
 * address derivation, so the claimed bc1q address is cryptographically bound
 * to the recovered public key — not merely a user-supplied string.
 *
 * Message hash: Bitcoin Signed Message convention, varint-prefixed (CompactSize),
 * NOT decimal-ASCII length prefixes:
 *   sha256d("\x18Bitcoin Signed Message:\n" + compactSize(len(msg)) + msg)
 * https://github.com/bitcoin/bitcoin/blob/master/src/util/message.cpp
 */
import { sha256 } from './noble/hashes/sha2.js';
import { ripemd160 } from './noble/hashes/ripemd160.js';
import { encodeSegwitAddress } from './bech32.js';
import * as secp from './noble/secp256k1/secp256k1.js';

secp.hashes.sha256 = sha256;

const MAGIC = '\x18Bitcoin Signed Message:\n';

function compactSize(n) {
  if (n < 0xfd) return new Uint8Array([n]);
  if (n <= 0xffff) return new Uint8Array([0xfd, n & 0xff, (n >> 8) & 0xff]);
  // messages this long never occur for our nonce payloads; keep it simple/correct up to 16-bit.
  throw new Error('message too long');
}

function sha256d(bytes) {
  return sha256(sha256(bytes));
}

function bitcoinMessageHash(message) {
  const enc = new TextEncoder();
  const magic = enc.encode(MAGIC);
  const msgBytes = enc.encode(message);
  const buf = new Uint8Array(magic.length + compactSize(msgBytes.length).length + msgBytes.length);
  let p = 0;
  buf.set(magic, p); p += magic.length;
  const cs = compactSize(msgBytes.length);
  buf.set(cs, p); p += cs.length;
  buf.set(msgBytes, p);
  return sha256d(buf);
}

function hash160(pubkeyBytes) {
  return ripemd160(sha256(pubkeyBytes));
}

/**
 * Verify a BIP-137 base64 signature over `message`, recover the signer's
 * public key, derive its P2WPKH (bc1q) address, and require it to equal
 * `claimedAddress`. Throws on any failure. Returns nothing on success.
 */
export function verifyBtcSignedMessage({ message, signatureBase64, claimedAddress }) {
  if (!message || !signatureBase64 || !claimedAddress) throw new Error('missing btc verification fields');
  const sig = Uint8Array.from(atob(signatureBase64), (c) => c.charCodeAt(0));
  if (sig.length !== 65) throw new Error('bad btc signature length');
  const header = sig[0];
  if (header < 27 || header > 42) throw new Error('bad btc signature header byte');
  // BIP-137 ranges: 27-30 P2PKH uncompressed, 31-34 P2PKH compressed,
  // 35-38 P2SH-P2WPKH compressed, 39-42 P2WPKH compressed.
  const recid = (header - 27) % 4;
  const compressed = header >= 31;
  if (!compressed) throw new Error('uncompressed keys unsupported for bech32 P2WPKH');

  const r = sig.slice(1, 33);
  const s = sig.slice(33, 65);
  // noble's "recovered" signature format is [recoveryByte, r(32), s(32)].
  const recoveredSig = new Uint8Array(65);
  recoveredSig[0] = recid;
  recoveredSig.set(r, 1);
  recoveredSig.set(s, 33);

  const digest = bitcoinMessageHash(message);
  const pubkey = secp.recoverPublicKey(recoveredSig, digest, { isCompressed: true, prehash: false });

  const hash = hash160(pubkey);
  const derivedAddress = encodeSegwitAddress('bc', 0, hash);
  if (derivedAddress !== claimedAddress) {
    throw new Error('recovered public key does not derive claimed address');
  }
}
