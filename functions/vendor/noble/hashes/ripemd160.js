/**
 * RIPEMD-160 (vendored from @noble/hashes src/legacy.ts, RIPEMD-160 section only, MIT).
 * Needed for Bitcoin HASH160 = ripemd160(sha256(pubkey)), not present in upstream dist here.
 * @module
 */
import { HashMD } from "./_md.js";
import { clean, createHasher, rotl } from "./utils.js";

const Rho160 = /* @__PURE__ */ Uint8Array.from([
  7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
]);
const Id160 = /* @__PURE__ */ (() => Uint8Array.from(new Array(16).fill(0).map((_, i) => i)))();
const Pi160 = /* @__PURE__ */ (() => Id160.map((i) => (9 * i + 5) % 16))();
const idxLR = /* @__PURE__ */ (() => {
  const L = [Id160];
  const R = [Pi160];
  const res = [L, R];
  for (let i = 0; i < 4; i++) for (const j of res) j.push(j[i].map((k) => Rho160[k]));
  return res;
})();
const idxL = idxLR[0];
const idxR = idxLR[1];

const shifts160 = /* @__PURE__ */ [
  [11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8],
  [12, 13, 11, 15, 6, 9, 9, 7, 12, 15, 11, 13, 7, 8, 7, 7],
  [13, 15, 14, 11, 7, 7, 6, 8, 13, 14, 13, 12, 5, 5, 6, 9],
  [14, 11, 12, 14, 8, 6, 5, 5, 15, 12, 15, 14, 9, 9, 8, 6],
  [15, 12, 13, 13, 9, 5, 8, 6, 14, 11, 12, 11, 8, 6, 5, 5],
].map((i) => Uint8Array.from(i));
const shiftsL160 = /* @__PURE__ */ idxL.map((idx, i) => idx.map((j) => shifts160[i][j]));
const shiftsR160 = /* @__PURE__ */ idxR.map((idx, i) => idx.map((j) => shifts160[i][j]));
const Kl160 = /* @__PURE__ */ Uint32Array.from([
  0x00000000, 0x5a827999, 0x6ed9eba1, 0x8f1bbcdc, 0xa953fd4e,
]);
const Kr160 = /* @__PURE__ */ Uint32Array.from([
  0x50a28be6, 0x5c4dd124, 0x6d703ef3, 0x7a6d76e9, 0x00000000,
]);
function ripemd_f(group, x, y, z) {
  if (group === 0) return x ^ y ^ z;
  if (group === 1) return (x & y) | (~x & z);
  if (group === 2) return (x | ~y) ^ z;
  if (group === 3) return (x & z) | (y & ~z);
  return x ^ (y | ~z);
}
const BUF_160 = /* @__PURE__ */ new Uint32Array(16);

class _RIPEMD160 extends HashMD {
  h0 = 0x67452301 | 0;
  h1 = 0xefcdab89 | 0;
  h2 = 0x98badcfe | 0;
  h3 = 0x10325476 | 0;
  h4 = 0xc3d2e1f0 | 0;

  constructor() {
    super(64, 20, 8, true);
  }
  get() {
    const { h0, h1, h2, h3, h4 } = this;
    return [h0, h1, h2, h3, h4];
  }
  set(h0, h1, h2, h3, h4) {
    this.h0 = h0 | 0;
    this.h1 = h1 | 0;
    this.h2 = h2 | 0;
    this.h3 = h3 | 0;
    this.h4 = h4 | 0;
  }
  _cloneInto(to) {
    (to ||= new _RIPEMD160()).set(...this.get());
    return this._cloneIntoMeta(to);
  }
  process(view, offset) {
    for (let i = 0; i < 16; i++, offset += 4) BUF_160[i] = view.getUint32(offset, true);
    let al = this.h0 | 0, ar = al,
        bl = this.h1 | 0, br = bl,
        cl = this.h2 | 0, cr = cl,
        dl = this.h3 | 0, dr = dl,
        el = this.h4 | 0, er = el;
    for (let group = 0; group < 5; group++) {
      const rGroup = 4 - group;
      const hbl = Kl160[group], hbr = Kr160[group];
      const rl = idxL[group], rr = idxR[group];
      const sl = shiftsL160[group], sr = shiftsR160[group];
      for (let i = 0; i < 16; i++) {
        const tl = (rotl(al + ripemd_f(group, bl, cl, dl) + BUF_160[rl[i]] + hbl, sl[i]) + el) | 0;
        al = el; el = dl; dl = rotl(cl, 10) | 0; cl = bl; bl = tl;
      }
      for (let i = 0; i < 16; i++) {
        const tr = (rotl(ar + ripemd_f(rGroup, br, cr, dr) + BUF_160[rr[i]] + hbr, sr[i]) + er) | 0;
        ar = er; er = dr; dr = rotl(cr, 10) | 0; cr = br; br = tr;
      }
    }
    this.set(
      (this.h1 + cl + dr) | 0,
      (this.h2 + dl + er) | 0,
      (this.h3 + el + ar) | 0,
      (this.h4 + al + br) | 0,
      (this.h0 + bl + cr) | 0
    );
  }
  roundClean() {
    clean(BUF_160);
  }
  destroy() {
    this.destroyed = true;
    clean(this.buffer);
    this.set(0, 0, 0, 0, 0);
  }
}

/** RIPEMD-160(msg) -> 20 bytes. */
export const ripemd160 = /* @__PURE__ */ createHasher(() => new _RIPEMD160());
