/**
 * Minimal TON BoC (Bag of Cells) parser + cell hashing.
 * Only what's needed to verify a wallet StateInit: parse cells, compute each
 * cell's representation hash (sha256 of descriptors+bits+ref depths+ref hashes),
 * per the standard TON cell serialization algorithm:
 * https://github.com/ton-org/ton-core/blob/main/src/boc/cell/serialization.ts
 * No exotic cells (pruned branch/merkle proof) support — not needed for wallet code/data cells.
 */
import { sha256 } from './noble/hashes/sha2.js';

class BitReader {
  constructor(bytes, bitLen) {
    this.bytes = bytes;
    this.bitLen = bitLen;
    this.pos = 0; // bit offset
  }
  loadUint(bits) {
    let v = 0;
    for (let i = 0; i < bits; i++) {
      const byteIdx = this.pos >> 3;
      const bitIdx = 7 - (this.pos & 7);
      const bit = (this.bytes[byteIdx] >> bitIdx) & 1;
      v = v * 2 + bit;
      this.pos++;
    }
    return v;
  }
  loadBit() {
    return this.loadUint(1);
  }
  // Load dataBytesize*8 raw bits (no padding stripping — caller slices if needed)
  loadBitsAsBytes(nBits) {
    const nBytes = Math.ceil(nBits / 8);
    const out = new Uint8Array(nBytes);
    for (let i = 0; i < nBits; i++) {
      const byteIdx = this.pos >> 3;
      const bitIdx = 7 - (this.pos & 7);
      const bit = (this.bytes[byteIdx] >> bitIdx) & 1;
      out[i >> 3] |= bit << (7 - (i & 7));
      this.pos++;
    }
    return out;
  }
  skip(bits) {
    this.pos += bits;
  }
}

function getHashesCount(levelMask) {
  let n = 0;
  let mask = levelMask & 7;
  for (let i = 0; i < 3; i++) {
    n += mask & 1;
    mask >>= 1;
  }
  return n + 1;
}

/** Parse a BoC buffer into an array of raw cells: { bitsLen, dataBytes, refs: number[] }. */
function parseCells(buf) {
  const r = new BitReader(buf, buf.length * 8);
  const magic = r.loadUint(32);
  if (magic !== 0xb5ee9c72) throw new Error('bad BoC magic');
  const hasIdx = r.loadBit();
  const hasCrc32c = r.loadBit();
  const hasCacheBits = r.loadBit();
  r.skip(2); // flags
  const sizeBytes = r.loadUint(3);
  const offsetBytes = r.loadUint(8);
  const cellsNum = r.loadUint(sizeBytes * 8);
  const rootsNum = r.loadUint(sizeBytes * 8);
  const absentNum = r.loadUint(sizeBytes * 8);
  r.loadUint(offsetBytes * 8); // tot_cells_size
  const roots = [];
  for (let i = 0; i < rootsNum; i++) roots.push(r.loadUint(sizeBytes * 8));
  if (hasIdx) {
    for (let i = 0; i < cellsNum; i++) r.loadUint(offsetBytes * 8);
  }
  const cells = [];
  for (let i = 0; i < cellsNum; i++) {
    const d1 = r.loadUint(8);
    const d2 = r.loadUint(8);
    const refsCount = d1 % 8;
    const levelMask = d1 >> 5;
    const hasHashesFlag = (d1 & 16) !== 0;
    const exotic = (d1 & 8) !== 0;
    if (hasHashesFlag) {
      const hc = getHashesCount(levelMask);
      r.skip(hc * 32 * 8); // stored hashes
      r.skip(hc * 2 * 8); // stored depths
    }
    const dataBytesize = Math.ceil(d2 / 2);
    const paddingAdded = (d2 % 2) === 1;
    const bitsLen = paddingAdded ? dataBytesize * 8 - trailingPaddingBits(r, dataBytesize) : dataBytesize * 8;
    // Load raw bytes first, strip padding after (simpler: compute bitsLen while reading)
    const raw = r.loadBitsAsBytes(dataBytesize * 8);
    const refs = [];
    for (let j = 0; j < refsCount; j++) refs.push(r.loadUint(sizeBytes * 8));
    cells.push({ raw, dataBytesize, paddingAdded, refs, exotic });
  }
  return { cells, roots };
}
// Padding bits are stripped from raw bytes at hash time, not at read time (keeps reader simple).
function trailingPaddingBits() {
  return 0; // unused; padding handled via computeBitsLen below
}

function computeBitsLen(raw, paddingAdded) {
  if (!paddingAdded) return raw.length * 8;
  // Find last set bit (the padding "1" terminator), bits before it are real data.
  for (let i = raw.length - 1; i >= 0; i--) {
    if (raw[i] === 0) continue;
    let b = raw[i];
    let trail = 0;
    while ((b & 1) === 0) { b >>= 1; trail++; }
    return i * 8 + (8 - trail - 1);
  }
  return 0;
}

function getBitsDescriptor(bitsLen) {
  return Math.ceil(bitsLen / 8) + Math.floor(bitsLen / 8);
}
function getRefsDescriptor(refsCount, levelMask, exotic) {
  return refsCount + (exotic ? 8 : 0) + levelMask * 32;
}

/** Parse BoC (Uint8Array) and return root cells with .hash (Uint8Array) and .bits {len,bytes}, .refs (resolved cell objects). */
export function parseBoc(buf) {
  const { cells: rawCells, roots } = parseCells(buf);
  const n = rawCells.length;
  const resolved = new Array(n);
  // Standard BoC serialization: children have a HIGHER index than parents (topological order).
  for (let i = n - 1; i >= 0; i--) {
    const c = rawCells[i];
    const bitsLen = computeBitsLen(c.raw, c.paddingAdded);
    const refCells = c.refs.map((idx) => resolved[idx]);
    for (const rc of refCells) {
      if (!rc) throw new Error('bad BoC: ref to unresolved cell (non-topological order)');
    }
    const d1 = getRefsDescriptor(c.refs.length, 0, c.exotic);
    const d2 = getBitsDescriptor(bitsLen);
    const bitsBytes = Math.ceil(bitsLen / 8);
    const repr = new Uint8Array(2 + bitsBytes + (2 + 32) * refCells.length);
    let p = 0;
    repr[p++] = d1;
    repr[p++] = d2;
    repr.set(c.raw.slice(0, bitsBytes), p);
    p += bitsBytes;
    for (const rc of refCells) {
      repr[p++] = (rc.depth >> 8) & 0xff;
      repr[p++] = rc.depth & 0xff;
    }
    for (const rc of refCells) {
      repr.set(rc.hash, p);
      p += 32;
    }
    const hash = sha256(repr);
    const depth = refCells.length ? Math.max(...refCells.map((rc) => rc.depth)) + 1 : 0;
    resolved[i] = { bitsLen, raw: c.raw, refs: refCells, hash, depth };
  }
  return roots.map((idx) => resolved[idx]);
}

/** BitReader over an already-resolved cell's raw bits (for reading StateInit / wallet data layout). */
export class CellReader {
  constructor(cell) {
    this.cell = cell;
    this.r = new BitReader(cell.raw, cell.bitsLen);
    this.refIdx = 0;
  }
  loadBit() { return this.r.loadBit(); }
  loadUint(bits) { return this.r.loadUint(bits); }
  loadBuffer(bytes) { return this.r.loadBitsAsBytes(bytes * 8); }
  nextRef() { return this.cell.refs[this.refIdx++]; }
}

export function bytesToHex(b) {
  let s = '';
  for (const x of b) s += x.toString(16).padStart(2, '0');
  return s;
}
