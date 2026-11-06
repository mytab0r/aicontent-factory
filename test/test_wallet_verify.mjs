import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyWalletSignature, normalizeAddress } from '../functions/lib/wallet-verify.js';
import { rawCellToTree, serializeBoc, bytesToBits, numToBits } from './helpers/ton-test-boc.mjs';
import { parseBoc, bytesToHex } from '../functions/vendor/ton-boc.js';
import * as ed from '../functions/vendor/noble/ed25519/ed25519.js';
import { sha256, sha512 } from '../functions/vendor/noble/hashes/sha2.js';
import { ripemd160 } from '../functions/vendor/noble/hashes/ripemd160.js';
import { encodeSegwitAddress } from '../functions/vendor/bech32.js';
import * as secp from '../functions/vendor/noble/secp256k1/secp256k1.js';

ed.hashes.sha512 = sha512;
secp.hashes.sha256 = sha256;
// hmac-sha256, needed only for deterministic signing in this test (verify path never signs).
function hmacSha256(key, msg) {
  const blockSize = 64;
  const k = key.length > blockSize ? sha256(key) : key;
  const padded = new Uint8Array(blockSize);
  padded.set(k);
  const ipad = new Uint8Array(blockSize);
  const opad = new Uint8Array(blockSize);
  for (let i = 0; i < blockSize; i++) { ipad[i] = padded[i] ^ 0x36; opad[i] = padded[i] ^ 0x5c; }
  const inner = sha256(new Uint8Array([...ipad, ...msg]));
  return sha256(new Uint8Array([...opad, ...inner]));
}
secp.hashes.hmacSha256 = (key, msg) => hmacSha256(key, msg);

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'vectors.json'), 'utf8'));
const MSG = V.msg;

assert.strictEqual(verifyWalletSignature({ chain: 'evm', message: MSG, signature: V.evm.sig, address: V.evm.addr }).address, V.evm.addr, 'EVM recovery');
assert.strictEqual(verifyWalletSignature({ chain: 'tron', message: MSG, signature: V.tron.sig, address: V.tron.addr }).address, V.tron.addr, 'TRON recovery');
assert.strictEqual(verifyWalletSignature({ chain: 'solana', message: MSG, signature: V.solana.sig, address: V.solana.addr }).address, V.solana.addr, 'SOL verify');

assert.throws(() => verifyWalletSignature({ chain: 'evm', message: MSG + 'x', signature: V.evm.sig, address: V.evm.addr }), 'EVM wrong msg must fail');
assert.throws(() => verifyWalletSignature({ chain: 'tron', message: MSG + 'x', signature: V.tron.sig, address: V.tron.addr }), 'TRON wrong msg must fail');
assert.throws(() => verifyWalletSignature({ chain: 'solana', message: MSG, signature: V.solana.sig, address: V.solana.addr.slice(0, -2) + 'zz' }), 'SOL wrong addr must fail');

assert.throws(() => verifyWalletSignature({ chain: 'evm', message: MSG, signature: V.evm.sig, address: '0x0000000000000000000000000000000000000000' }), 'EVM address mismatch must fail');
assert.throws(() => verifyWalletSignature({ chain: 'tron', message: MSG, signature: V.tron.sig, address: 'TXXXXXX' }), 'TRON address mismatch must fail');

assert.throws(() => verifyWalletSignature({ chain: 'evm', message: MSG, signature: V.evm.sig.slice(0, -2) + 'ff' }), 'EVM bad v must fail');
assert.throws(() => verifyWalletSignature({ chain: 'tron', message: MSG, signature: '0x00' + V.tron.sig.slice(4) }), 'TRON bad recovery must fail');

assert.throws(() => verifyWalletSignature({ chain: 'evm', message: 'random site msg', signature: V.evm.sig }), 'foreign message must fail');

assert.strictEqual(normalizeAddress('evm', '0xABCdef'), '0xabcdef');
assert.strictEqual(normalizeAddress('tron', 'TCvZ'), 'TCvZ');

// --- BTC: BIP-137 signed message, P2WPKH (bc1q) only, derived address must match claim ---
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
function signBtc(message, priv) {
  const digest = bitcoinMessageHash(message);
  const sig = secp.sign(digest, priv, { format: 'recovered', prehash: false });
  const header = 39 + sig[0];
  const bip137 = new Uint8Array(65);
  bip137[0] = header;
  bip137.set(sig.slice(1), 1);
  return Buffer.from(bip137).toString('base64');
}

const btcPriv = secp.utils.randomSecretKey();
const btcPub = secp.getPublicKey(btcPriv, true);
const btcAddr = encodeSegwitAddress('bc', 0, ripemd160(sha256(btcPub)));
const btcSig = signBtc(MSG, btcPriv);

assert.strictEqual(verifyWalletSignature({ chain: 'btc', message: MSG, signature: btcSig, address: btcAddr }).address, btcAddr, 'BTC recovery');
assert.throws(() => verifyWalletSignature({ chain: 'btc', message: MSG, signature: btcSig, address: 'bc1q' + 'x'.repeat(38) }), 'BTC address mismatch must fail');
assert.throws(() => verifyWalletSignature({ chain: 'btc', message: MSG + 'x', signature: btcSig, address: btcAddr }), 'BTC tampered message must fail');
const otherBtcPriv = secp.utils.randomSecretKey();
assert.throws(() => verifyWalletSignature({ chain: 'btc', message: MSG, signature: signBtc(MSG, otherBtcPriv), address: btcAddr }), 'BTC impersonation must fail');

// --- TON: TonConnect ton_proof, key trust from parsed walletStateInit (never from client) ---
const V4R2_CODE_B64 = 'te6ccgECFAEAAtQAART/APSkE/S88sgLAQIBIAIDAgFIBAUE+PKDCNcYINMf0x/THwL4I7vyZO1E0NMf0x/T//QE0VFDuvKhUVG68qIF+QFUEGT5EPKj+AAkpMjLH1JAyx9SMMv/UhD0AMntVPgPAdMHIcAAn2xRkyDXSpbTB9QC+wDoMOAhwAHjACHAAuMAAcADkTDjDQOkyMsfEssfy/8QERITAubQAdDTAyFxsJJfBOAi10nBIJJfBOAC0x8hghBwbHVnvSKCEGRzdHK9sJJfBeAD+kAwIPpEAcjKB8v/ydDtRNCBAUDXIfQEMFyBAQj0Cm+hMbOSXwfgBdM/yCWCEHBsdWe6kjgw4w0DghBkc3RyupJfBuMNBgcCASAICQB4AfoA9AQw+CdvIjBQCqEhvvLgUIIQcGx1Z4MesXCAGFAEywUmzxZY+gIZ9ADLaRfLH1Jgyz8gyYBA+wAGAIpQBIEBCPRZMO1E0IEBQNcgyAHPFvQAye1UAXKwjiOCEGRzdHKDHrFwgBhQBcsFUAPPFiP6AhPLassfyz/JgED7AJJfA+ICASAKCwBZvSQrb2omhAgKBrkPoCGEcNQICEekk30pkQzmkD6f+YN4EoAbeBAUiYcVnzGEAgFYDA0AEbjJftRNDXCx+AA9sp37UTQgQFA1yH0BDACyMoHy//J0AGBAQj0Cm+hMYAIBIA4PABmtznaiaEAga5Drhf/AABmvHfaiaEAQa5DrhY/AAG7SB/oA1NQi+QAFyMoHFcv/ydB3dIAYyMsFywIizxZQBfoCFMtrEszMyXP7AMhAFIEBCPRR8qcCAHCBAQjXGPoA0z/IVCBHgQEI9FHyp4IQbm90ZXB0gBjIywXLAlAGzxZQBPoCFMtqEssfyz/Jc/sAAgBsgQEI1xj6ANM/MFIkgQEI9Fnyp4IQZHN0cnB0gBjIywXLAlAFzxZQA/oCE8tqyx8Syz/Jc/sAAAr0AMntVA==';
const codeRoot = parseBoc(Uint8Array.from(Buffer.from(V4R2_CODE_B64, 'base64')))[0];
const codeTree = rawCellToTree(codeRoot);

const tonPriv = ed.utils.randomSecretKey();
const tonPub = ed.getPublicKey(tonPriv);
const WALLET_ID = 698983191;
const dataTree = { bits: [...numToBits(0, 32), ...numToBits(WALLET_ID, 32), ...bytesToBits(tonPub), 0], refs: [] };
const stateInitRoot = { bits: [0, 0, 1, 1, 0], refs: [codeTree, dataTree] };
const stateInitB64 = Buffer.from(serializeBoc(stateInitRoot)).toString('base64');
const parsedBack = parseBoc(serializeBoc(stateInitRoot))[0];
const tonAddress = `0:${bytesToHex(parsedBack.hash)}`;

function signTonProof({ domain, timestamp, payload }) {
  const enc = new TextEncoder();
  const wc = new Uint8Array(4); new DataView(wc.buffer).setInt32(0, 0, false);
  const domainBytes = enc.encode(domain);
  const dl = new Uint8Array(4); new DataView(dl.buffer).setUint32(0, domainBytes.length, true);
  const tsBuf = new Uint8Array(8); new DataView(tsBuf.buffer).setBigUint64(0, BigInt(timestamp), true);
  const msg = new Uint8Array([...enc.encode('ton-proof-item-v2/'), ...wc, ...parsedBack.hash, ...dl, ...domainBytes, ...tsBuf, ...enc.encode(payload)]);
  const digest = sha256(new Uint8Array([0xff, 0xff, ...enc.encode('ton-connect'), ...sha256(msg)]));
  return Buffer.from(ed.sign(digest, tonPriv)).toString('base64');
}

const tonNonce = 'test-nonce-123';
const tonTs = Math.floor(Date.now() / 1000);
const tonSig = signTonProof({ domain: 'pay.pxbt.app', timestamp: tonTs, payload: tonNonce });
const tonSignaturePayload = JSON.stringify({ address: tonAddress, stateInit: stateInitB64, proof: { domain: 'pay.pxbt.app', timestamp: tonTs, payload: tonNonce, signature: tonSig } });

assert.doesNotThrow(() => verifyWalletSignature({ chain: 'ton', message: tonNonce, signature: tonSignaturePayload }), 'TON proof must verify');
assert.throws(() => verifyWalletSignature({ chain: 'ton', message: 'wrong-nonce', signature: tonSignaturePayload }), 'TON payload/nonce mismatch must fail');
const forgedTonSig = JSON.stringify({ address: tonAddress, stateInit: stateInitB64, proof: { domain: 'pay.pxbt.app', timestamp: tonTs, payload: tonNonce, signature: Buffer.from(ed.sign(sha256(new Uint8Array(32)), ed.utils.randomSecretKey())).toString('base64') } });
assert.throws(() => verifyWalletSignature({ chain: 'ton', message: tonNonce, signature: forgedTonSig }), 'TON forged signature must fail');
const spoofedAddrSig = JSON.stringify({ address: '0:' + '00'.repeat(32), stateInit: stateInitB64, proof: { domain: 'pay.pxbt.app', timestamp: tonTs, payload: tonNonce, signature: tonSig } });
assert.throws(() => verifyWalletSignature({ chain: 'ton', message: tonNonce, signature: spoofedAddrSig }), 'TON address spoof must fail');

console.log('wallet-verify: all OK');
