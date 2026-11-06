/**
 * TON wallet verification: parse walletStateInit, derive address + public key
 * from KNOWN wallet contract code (no external API call, no trusted-third-party
 * lookup needed) — the address itself is the sha256 hash of the StateInit cell,
 * so deriving it from the client-supplied state_init and comparing against the
 * claimed address is a self-contained cryptographic check (TON Connect spec
 * step 2.1-2.3: https://github.com/ton-blockchain/ton-connect/blob/main/requests-responses.md).
 *
 * The public key is extracted from the parsed wallet DATA cell, never taken
 * from the client's `public_key` field directly — that field is only used as
 * an equality check, binding the TonProof signature to the address-derived key.
 */
import { parseBoc, bytesToHex } from './ton-boc.js';
import { sha256 } from './noble/hashes/sha2.js';
import * as ed from './noble/ed25519/ed25519.js';
import { sha512 } from './noble/hashes/sha2.js';

ed.hashes.sha512 = sha512;

// Official standard-wallet code hashes (sha256 of code cell), per
// https://docs.ton.org/contracts/standard/wallets/history — data-layout per version.
const WALLET_LAYOUTS = {
  'a0cfc2c48aee16a271f2cfc0b7382d81756cecb1017d077faaab3bb602f6868c': 'v1', // V1R1
  'd4902fcc9fad74698fa8e353220a68da0dcf72e32bcb2eb9ee04217c17d3062c': 'v1', // V1R2
  '587cc789eff1c84f46ec3797e45fc809a14ff5ae24f1e0c7a6a99cc9dc9061ff': 'v1', // V1R3
  '5c9a5e68c108e18721a07c42f9956bfb39ad77ec6d624b60c576ec88eee65329': 'v1', // V2R1
  'fe9530d3243853083ef2ef0b4c2908c0abf6fa1c31ea243aacaa5bf8c7d753f1': 'v1', // V2R2
  'b61041a58a7980b946e8fb9e198e3c904d24799ffa36574ea4251c41a566f581': 'v3', // V3R1
  '84dafa449f98a6987789ba232358072bc0f76dc4524002a5d0918b9a75d2d599': 'v3', // V3R2
  '64dd54805522c5be8a9db59cea0105ccf0d08786ca79beb8cb79e880a8d7322d': 'v4', // V4R1
  'feb5ff6820e2ff0d9483e7e0d62c817d846789fb4ae580c878866d959dabd5c0': 'v4', // V4R2
  '20834b7b72b112147e1b2fb457b84e74d1a30f04f737d4f62a668e9552d2b72f': 'v5', // V5R1
};

const CRC16_TAB = (() => {
  const tab = new Uint16Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i << 8;
    for (let j = 0; j < 8; j++) c = (c & 0x8000) ? ((c << 1) ^ 0x1021) & 0xffff : (c << 1) & 0xffff;
    tab[i] = c;
  }
  return tab;
})();
function crc16(bytes) {
  let crc = 0;
  for (const b of bytes) crc = ((crc << 8) & 0xffff) ^ CRC16_TAB[((crc >> 8) ^ b) & 0xff];
  return crc;
}

const B64URL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
function b64urlEncode(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i], b1 = bytes[i + 1], b2 = bytes[i + 2];
    s += B64URL[b0 >> 2];
    s += B64URL[((b0 & 3) << 4) | (b1 === undefined ? 0 : b1 >> 4)];
    if (b1 === undefined) break;
    s += B64URL[((b1 & 15) << 2) | (b2 === undefined ? 0 : b2 >> 6)];
    if (b2 === undefined) break;
    s += B64URL[b2 & 63];
  }
  return s;
}
function b64urlDecode(s) {
  const rev = {};
  for (let i = 0; i < B64URL.length; i++) rev[B64URL[i]] = i;
  const clean = s.replace(/=+$/, '');
  const out = [];
  let buf = 0, bits = 0;
  for (const c of clean) {
    if (!(c in rev)) throw new Error('bad base64url char');
    buf = (buf << 6) | rev[c];
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push((buf >> bits) & 0xff);
    }
  }
  return new Uint8Array(out);
}

/** Non-bounceable (UQ) user-friendly address, mainnet. Matches /admin placeholder "UQ...". */
export function toFriendlyAddress(workchain, hashBytes) {
  const tag = 0x51; // non-bounceable, mainnet
  const buf = new Uint8Array(34);
  buf[0] = tag;
  buf[1] = workchain & 0xff;
  buf.set(hashBytes, 2);
  const crc = crc16(buf);
  const full = new Uint8Array(36);
  full.set(buf, 0);
  full[34] = (crc >> 8) & 0xff;
  full[35] = crc & 0xff;
  return b64urlEncode(full);
}

/** Parse "0:hex..." raw TON address (format mandated by TonProof protocol for proof.address / TonAddressItemReply.address). */
export function parseRawAddress(address) {
  const m = /^(-?\d+):([0-9a-fA-F]{64})$/.exec(String(address || '').trim());
  if (!m) throw new Error('ton address must be raw "workchain:hex" format');
  return { workchain: parseInt(m[1], 10), hash: hexToBytes(m[2]) };
}
function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

/**
 * Parse a base64 BoC containing a StateInit cell (split_depth/special/library
 * absent — true for every standard wallet contract) into {codeHash, dataCell}.
 */
function parseStateInit(stateInitB64) {
  const buf = Uint8Array.from(atob(stateInitB64), (c) => c.charCodeAt(0));
  const [root] = parseBoc(buf);
  const r = { pos: 0, cell: root };
  const bit = () => {
    const byteIdx = r.pos >> 3;
    const bitIdx = 7 - (r.pos & 7);
    const v = (root.raw[byteIdx] >> bitIdx) & 1;
    r.pos++;
    return v;
  };
  if (bit() !== 0) throw new Error('split_depth stateInit unsupported');
  if (bit() !== 0) throw new Error('special stateInit unsupported');
  const hasCode = bit();
  const hasData = bit();
  const hasLib = bit();
  if (!hasCode || !hasData || hasLib) throw new Error('stateInit must have code+data, no library');
  const [codeCell, dataCell] = root.refs;
  if (!codeCell || !dataCell) throw new Error('stateInit missing code/data refs');
  return { addressHash: root.hash, codeCell, dataCell };
}

function dataBitReader(cell) {
  let pos = 0;
  return {
    loadBit() {
      const byteIdx = pos >> 3;
      const bitIdx = 7 - (pos & 7);
      const v = (cell.raw[byteIdx] >> bitIdx) & 1;
      pos++;
      return v;
    },
    loadUint(bits) {
      let v = 0;
      for (let i = 0; i < bits; i++) v = v * 2 + this.loadBit();
      return v;
    },
    loadBuffer(nBytes) {
      const out = new Uint8Array(nBytes);
      for (let i = 0; i < nBytes * 8; i++) out[i >> 3] |= this.loadBit() << (7 - (i & 7));
      return out;
    },
  };
}

/** Extract the ed25519 public key from a standard wallet's data cell, per its layout. */
function extractPublicKey(dataCell, layout) {
  const r = dataBitReader(dataCell);
  if (layout === 'v1') {
    r.loadUint(32); // seqno
    return r.loadBuffer(32);
  }
  if (layout === 'v3' || layout === 'v4') {
    r.loadUint(32); // seqno
    r.loadUint(32); // wallet_id
    return r.loadBuffer(32);
  }
  if (layout === 'v5') {
    r.loadBit(); // is_signature_auth_allowed
    r.loadUint(32); // seqno
    r.loadUint(32); // wallet_id
    return r.loadBuffer(32);
  }
  throw new Error('unknown wallet layout');
}

/**
 * Verify a TonProof (TON Connect ton_proof) end to end:
 *  1. Parse walletStateInit -> derive address hash + identify wallet code.
 *  2. Derived address must equal the claimed address (binds StateInit to address).
 *  3. Extract the real public key from the DATA cell (never trust client publicKey).
 *  4. Verify Ed25519 signature over the TonProof message digest with that key.
 * Returns the UQ-format address on success, throws on any mismatch.
 */
export function verifyTonProof({ address, stateInit, proof }, { domain }) {
  if (!address || !stateInit || !proof) throw new Error('missing ton proof fields');
  const { workchain, hash: claimedHash } = parseRawAddress(address);
  const { addressHash, codeCell, dataCell } = parseStateInit(stateInit);
  if (bytesToHex(addressHash) !== bytesToHex(claimedHash)) {
    throw new Error('stateInit does not derive claimed address');
  }
  const codeHashHex = bytesToHex(codeCell.hash);
  const layout = WALLET_LAYOUTS[codeHashHex];
  if (!layout) throw new Error('unrecognized wallet contract code');
  const publicKey = extractPublicKey(dataCell, layout);

  if (typeof proof.domain !== 'string' || proof.domain !== domain) {
    throw new Error('domain mismatch');
  }
  const now = Math.floor(Date.now() / 1000);
  const ts = Number(proof.timestamp);
  if (!Number.isFinite(ts) || Math.abs(now - ts) > 15 * 60) throw new Error('proof timestamp expired');
  if (typeof proof.payload !== 'string' || proof.payload.length > 256) throw new Error('bad proof payload');

  const enc = new TextEncoder();
  const wc = new Uint8Array(4);
  new DataView(wc.buffer).setInt32(0, workchain, false);
  const domainBytes = enc.encode(domain);
  const dl = new Uint8Array(4);
  new DataView(dl.buffer).setUint32(0, domainBytes.length, true);
  const tsBuf = new Uint8Array(8);
  new DataView(tsBuf.buffer).setBigUint64(0, BigInt(ts), true);
  const payloadBytes = enc.encode(proof.payload);

  const msg = new Uint8Array([
    ...enc.encode('ton-proof-item-v2/'),
    ...wc,
    ...claimedHash,
    ...dl,
    ...domainBytes,
    ...tsBuf,
    ...payloadBytes,
  ]);
  const msgHash = sha256(msg);
  const fullMsg = new Uint8Array([0xff, 0xff, ...enc.encode('ton-connect'), ...msgHash]);
  const digest = sha256(fullMsg);

  const sig = Uint8Array.from(atob(proof.signature), (c) => c.charCodeAt(0));
  if (!ed.verify(sig, digest, publicKey)) throw new Error('bad ton_proof signature');

  return toFriendlyAddress(workchain, claimedHash);
}
