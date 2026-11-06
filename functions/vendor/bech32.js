/**
 * Minimal Bech32 (BIP-173) encoder, segwit v0 only, for deriving bc1q P2WPKH
 * addresses from a 20-byte HASH160. No dependency: ~40 lines of stdlib bit math.
 * ponytail: bech32m (BIP-350, segwit v1+/taproot) not implemented — add if bc1p
 * addresses are ever needed; P2WPKH only uses bech32 (not bech32m).
 */
const CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";

function polymod(values) {
  const GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
  let chk = 1;
  for (const v of values) {
    const top = chk >>> 25;
    chk = ((chk & 0x1ffffff) << 5) ^ v;
    for (let i = 0; i < 5; i++) if ((top >>> i) & 1) chk ^= GEN[i];
  }
  return chk >>> 0;
}

function hrpExpand(hrp) {
  const out = [];
  for (const c of hrp) out.push(c.charCodeAt(0) >>> 5);
  out.push(0);
  for (const c of hrp) out.push(c.charCodeAt(0) & 31);
  return out;
}

function createChecksum(hrp, data) {
  const values = [...hrpExpand(hrp), ...data, 0, 0, 0, 0, 0, 0];
  const mod = polymod(values) ^ 1;
  const ret = [];
  for (let p = 0; p < 6; p++) ret.push((mod >>> (5 * (5 - p))) & 31);
  return ret;
}

/** Re-pack bytes (8-bit groups) into 5-bit groups for bech32 data encoding. */
function convertBits(data, fromBits, toBits, pad) {
  let acc = 0, bits = 0;
  const ret = [];
  const maxv = (1 << toBits) - 1;
  for (const value of data) {
    if (value < 0 || value >>> fromBits !== 0) return null;
    acc = (acc << fromBits) | value;
    bits += fromBits;
    while (bits >= toBits) {
      bits -= toBits;
      ret.push((acc >>> bits) & maxv);
    }
  }
  if (pad) {
    if (bits > 0) ret.push((acc << (toBits - bits)) & maxv);
  } else if (bits >= fromBits || ((acc << (toBits - bits)) & maxv)) {
    return null;
  }
  return ret;
}

/**
 * Encode a segwit v0 program (20-byte pubkey hash or 32-byte script hash)
 * into a bech32 address, e.g. encodeSegwitAddress('bc', 0, hash160Bytes).
 */
export function encodeSegwitAddress(hrp, witver, witprog) {
  const data = [witver, ...convertBits(Array.from(witprog), 8, 5, true)];
  const checksum = createChecksum(hrp, data);
  const combined = [...data, ...checksum];
  return hrp + "1" + combined.map((d) => CHARSET[d]).join("");
}
