// Generic minimal BoC serializer: build a boc from a tree of {bits:number[], refs:[]} cells,
// single root, no library/exotic cells, no dedup (test-only, not used by prod verifier).
// TON cell data bytes must be byte-aligned; non-multiple-of-8 bit counts get a
// "1" terminator bit then zero padding (the augmented-bits rule from the spec),
// which the parser's computeBitsLen() relies on to recover the exact bit length.
function bitsToBytes(bits) {
  const padded = bits.length % 8 === 0 ? bits : [...bits, 1, ...Array(7 - (bits.length % 8)).fill(0)];
  const out = new Uint8Array(Math.ceil(padded.length / 8));
  for (let i = 0; i < padded.length; i++) if (padded[i]) out[i >> 3] |= 1 << (7 - (i & 7));
  return out;
}
class BB {
  constructor() { this.bits = []; }
  writeBit(b) { this.bits.push(b ? 1 : 0); return this; }
  writeUint(v, n) { for (let i = n - 1; i >= 0; i--) this.bits.push((Number(v) >> i) & 1); return this; }
}

export function rawCellToTree(cell) {
  const bits = [];
  for (let i = 0; i < cell.bitsLen; i++) {
    const byteIdx = i >> 3, bitIdx = 7 - (i & 7);
    bits.push((cell.raw[byteIdx] >> bitIdx) & 1);
  }
  return { bits, refs: cell.refs.map(rawCellToTree) };
}

export function serializeBoc(root) {
  // post-order flatten so every ref index > its own index (children must come after? Actually our
  // ton-boc.js parser just resolves ref index into the cells array built in file order — any order
  // works as long as indices point to valid array slots). We flatten root-first, children after.
  const cells = [];
  function flatten(cell) {
    const idx = cells.length;
    cells.push({ bits: cell.bits, childRefs: [] });
    const childIdxs = cell.refs.map(flatten);
    cells[idx].childRefs = childIdxs;
    return idx;
  }
  flatten(root);

  function cellBytes(c) {
    const d1 = c.childRefs.length;
    const bitsLen = c.bits.length;
    const d2 = Math.ceil(bitsLen / 8) + Math.floor(bitsLen / 8);
    const bytes = bitsToBytes(c.bits);
    const parts = [new Uint8Array([d1, d2]), bytes];
    for (const idx of c.childRefs) parts.push(new Uint8Array([idx]));
    let total = 0; for (const p of parts) total += p.length;
    const out = new Uint8Array(total); let off = 0;
    for (const p of parts) { out.set(p, off); off += p.length; }
    return out;
  }
  const cellsBytes = cells.map(cellBytes);
  let totalCellSize = 0;
  for (const c of cellsBytes) totalCellSize += c.length;
  const sizeBytes = 1, offsetBytes = 2;
  const header = new BB();
  header.writeUint(0xb5ee9c72, 32);
  header.writeBit(0); header.writeBit(0); header.writeBit(0);
  header.writeUint(0, 2);
  header.writeUint(sizeBytes, 3);
  header.writeUint(offsetBytes, 8);
  header.writeUint(cells.length, sizeBytes * 8);
  header.writeUint(1, sizeBytes * 8);
  header.writeUint(0, sizeBytes * 8);
  header.writeUint(totalCellSize, offsetBytes * 8);
  header.writeUint(0, sizeBytes * 8);
  const headerBytes = bitsToBytes(header.bits);
  const out = new Uint8Array(headerBytes.length + totalCellSize);
  out.set(headerBytes, 0);
  let off = headerBytes.length;
  for (const c of cellsBytes) { out.set(c, off); off += c.length; }
  return out;
}

export function bytesToBits(bytes) {
  const bits = [];
  for (const b of bytes) for (let i = 7; i >= 0; i--) bits.push((b >> i) & 1);
  return bits;
}
export function numToBits(v, n) {
  const bits = [];
  for (let i = n - 1; i >= 0; i--) bits.push((Number(v) >> i) & 1);
  return bits;
}
