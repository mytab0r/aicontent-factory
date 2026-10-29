import { sha256 } from '../functions/vendor/noble/hashes/sha2.js';
import { ripemd160 } from '../functions/vendor/noble/hashes/ripemd160.js';
import { encodeSegwitAddress } from '../functions/vendor/bech32.js';
import * as secp from '../functions/vendor/noble/secp256k1/secp256k1.js';
import { verifyBtcSignedMessage } from '../functions/vendor/btc-verify.js';

secp.hashes.sha256 = sha256;

// hmac-sha256, needed only for deterministic signing in this test (verify path
// never signs). Minimal RFC 2104 construction over the vendored sha256.
function hmacSha256(key, msg) {
  const blockSize = 64;
  let k = key.length > blockSize ? sha256(key) : key;
  const padded = new Uint8Array(blockSize);
  padded.set(k);
  const ipad = new Uint8Array(blockSize);
  const opad = new Uint8Array(blockSize);
  for (let i = 0; i < blockSize; i++) { ipad[i] = padded[i] ^ 0x36; opad[i] = padded[i] ^ 0x5c; }
  const inner = sha256(new Uint8Array([...ipad, ...msg]));
  return sha256(new Uint8Array([...opad, ...inner]));
}
secp.hashes.hmacSha256 = (key, msg) => hmacSha256(key, msg);


function sha256d(b) { return sha256(sha256(b)); }
function bitcoinMessageHash(message) {
  const enc = new TextEncoder();
  const magic = enc.encode('\x18Bitcoin Signed Message:\n');
  const msgBytes = enc.encode(message);
  const cs = msgBytes.length < 0xfd ? new Uint8Array([msgBytes.length]) : new Uint8Array([0xfd, msgBytes.length & 0xff, (msgBytes.length >> 8) & 0xff]);
  const buf = new Uint8Array(magic.length + cs.length + msgBytes.length);
  let p = 0;
  buf.set(magic, p); p += magic.length;
  buf.set(cs, p); p += cs.length;
  buf.set(msgBytes, p);
  return sha256d(buf);
}

function main() {
  const priv = secp.utils.randomSecretKey();
  const pub = secp.getPublicKey(priv, true); // compressed
  const hash = ripemd160(sha256(pub));
  const address = encodeSegwitAddress('bc', 0, hash);

  const message = 'claim-nonce-abc123';
  const digest = bitcoinMessageHash(message);
  const sig = secp.sign(digest, priv, { format: 'recovered', prehash: false });
  // sig = [recoveryByte, r(32), s(32)] ; BIP-137 header = 27 + 4 (compressed P2WPKH range) + recid
  const header = 39 + sig[0];
  const bip137 = new Uint8Array(65);
  bip137[0] = header;
  bip137.set(sig.slice(1), 1);
  const signatureBase64 = Buffer.from(bip137).toString('base64');

  verifyBtcSignedMessage({ message, signatureBase64, claimedAddress: address });
  console.log('PASS valid signature verifies, address:', address);

  // tamper: wrong claimed address
  try {
    verifyBtcSignedMessage({ message, signatureBase64, claimedAddress: 'bc1qxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' });
    throw new Error('should reject mismatched address');
  } catch (e) { console.log('PASS rejected address mismatch:', e.message); }

  // tamper: different message than signed (replay/mutation attempt)
  try {
    verifyBtcSignedMessage({ message: 'different-message', signatureBase64, claimedAddress: address });
    throw new Error('should reject mismatched message');
  } catch (e) { console.log('PASS rejected tampered message:', e.message); }

  // tamper: signature from a different key claiming same address (impersonation)
  const otherPriv = secp.utils.randomSecretKey();
  const otherDigest = bitcoinMessageHash(message);
  const otherSig = secp.sign(otherDigest, otherPriv, { format: 'recovered', prehash: false });
  const otherHeader = 39 + otherSig[0];
  const otherBip137 = new Uint8Array(65);
  otherBip137[0] = otherHeader;
  otherBip137.set(otherSig.slice(1), 1);
  const otherSigB64 = Buffer.from(otherBip137).toString('base64');
  try {
    verifyBtcSignedMessage({ message, signatureBase64: otherSigB64, claimedAddress: address });
    throw new Error('should reject impersonation');
  } catch (e) { console.log('PASS rejected impersonation:', e.message); }

  console.log('ALL BTC VERIFY TESTS PASSED');
}

main();
