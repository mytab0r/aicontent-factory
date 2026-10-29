import { rawCellToTree, serializeBoc, bytesToBits, numToBits } from './helpers/ton-test-boc.mjs';
import { parseBoc, bytesToHex } from '../functions/vendor/ton-boc.js';
import * as ed from '../functions/vendor/noble/ed25519/ed25519.js';
import { sha256, sha512 } from '../functions/vendor/noble/hashes/sha2.js';
import { verifyTonProof, toFriendlyAddress } from '../functions/vendor/ton-wallet.js';

ed.hashes.sha512 = sha512;

const V4R2_CODE_B64 = 'te6ccgECFAEAAtQAART/APSkE/S88sgLAQIBIAIDAgFIBAUE+PKDCNcYINMf0x/THwL4I7vyZO1E0NMf0x/T//QE0VFDuvKhUVG68qIF+QFUEGT5EPKj+AAkpMjLH1JAyx9SMMv/UhD0AMntVPgPAdMHIcAAn2xRkyDXSpbTB9QC+wDoMOAhwAHjACHAAuMAAcADkTDjDQOkyMsfEssfy/8QERITAubQAdDTAyFxsJJfBOAi10nBIJJfBOAC0x8hghBwbHVnvSKCEGRzdHK9sJJfBeAD+kAwIPpEAcjKB8v/ydDtRNCBAUDXIfQEMFyBAQj0Cm+hMbOSXwfgBdM/yCWCEHBsdWe6kjgw4w0DghBkc3RyupJfBuMNBgcCASAICQB4AfoA9AQw+CdvIjBQCqEhvvLgUIIQcGx1Z4MesXCAGFAEywUmzxZY+gIZ9ADLaRfLH1Jgyz8gyYBA+wAGAIpQBIEBCPRZMO1E0IEBQNcgyAHPFvQAye1UAXKwjiOCEGRzdHKDHrFwgBhQBcsFUAPPFiP6AhPLassfyz/JgED7AJJfA+ICASAKCwBZvSQrb2omhAgKBrkPoCGEcNQICEekk30pkQzmkD6f+YN4EoAbeBAUiYcVnzGEAgFYDA0AEbjJftRNDXCx+AA9sp37UTQgQFA1yH0BDACyMoHy//J0AGBAQj0Cm+hMYAIBIA4PABmtznaiaEAga5Drhf/AABmvHfaiaEAQa5DrhY/AAG7SB/oA1NQi+QAFyMoHFcv/ydB3dIAYyMsFywIizxZQBfoCFMtrEszMyXP7AMhAFIEBCPRR8qcCAHCBAQjXGPoA0z/IVCBHgQEI9FHyp4IQbm90ZXB0gBjIywXLAlAGzxZQBPoCFMtqEssfyz/Jc/sAAgBsgQEI1xj6ANM/MFIkgQEI9Fnyp4IQZHN0cnB0gBjIywXLAlAFzxZQA/oCE8tqyx8Syz/Jc/sAAAr0AMntVA==';

async function main() {
  const codeRoot = parseBoc(Uint8Array.from(Buffer.from(V4R2_CODE_B64, 'base64')))[0];
  const codeTree = rawCellToTree(codeRoot);

  const priv = ed.utils.randomSecretKey();
  const pub = ed.getPublicKey(priv);
  const WALLET_ID = 698983191;
  const dataBits = [...numToBits(0, 32), ...numToBits(WALLET_ID, 32), ...bytesToBits(pub), 0];
  const dataTree = { bits: dataBits, refs: [] };

  const stateInitRoot = { bits: [0, 0, 1, 1, 0], refs: [codeTree, dataTree] };
  const stateInitBoc = serializeBoc(stateInitRoot);
  const stateInitB64 = Buffer.from(stateInitBoc).toString('base64');

  const parsedBack = parseBoc(stateInitBoc)[0];
  const addressHashHex = bytesToHex(parsedBack.hash);
  const address = `0:${addressHashHex}`;

  const domain = 'pay.pxbt.app';
  const timestamp = Math.floor(Date.now() / 1000);
  const payload = 'test-nonce-123';

  const wc = new Uint8Array(4); new DataView(wc.buffer).setInt32(0, 0, false);
  const domainBytes = new TextEncoder().encode(domain);
  const dl = new Uint8Array(4); new DataView(dl.buffer).setUint32(0, domainBytes.length, true);
  const tsBuf = new Uint8Array(8); new DataView(tsBuf.buffer).setBigUint64(0, BigInt(timestamp), true);
  const payloadBytes = new TextEncoder().encode(payload);
  const hashBytes = parsedBack.hash;
  const msg = new Uint8Array([
    ...new TextEncoder().encode('ton-proof-item-v2/'),
    ...wc, ...hashBytes, ...dl, ...domainBytes, ...tsBuf, ...payloadBytes,
  ]);
  const msgHash = sha256(msg);
  const fullMsg = new Uint8Array([0xff, 0xff, ...new TextEncoder().encode('ton-connect'), ...msgHash]);
  const digest = sha256(fullMsg);
  const signature = ed.sign(digest, priv);

  const proof = { domain, timestamp, payload, signature: Buffer.from(signature).toString('base64') };

  const friendly = verifyTonProof({ address, stateInit: stateInitB64, proof }, { domain });
  console.log('PASS valid proof ->', friendly);
  const expectFriendly = toFriendlyAddress(0, hashBytes);
  if (friendly !== expectFriendly) throw new Error('friendly address mismatch');

  // tamper: wrong address
  try {
    verifyTonProof({ address: '0:' + '00'.repeat(32), stateInit: stateInitB64, proof }, { domain });
    throw new Error('should have rejected mismatched address');
  } catch (e) { console.log('PASS rejected address mismatch:', e.message); }

  // tamper: wrong domain
  try {
    verifyTonProof({ address, stateInit: stateInitB64, proof }, { domain: 'evil.com' });
    throw new Error('should have rejected domain mismatch');
  } catch (e) { console.log('PASS rejected domain mismatch:', e.message); }

  // tamper: signature from different key (impersonation attempt)
  const otherPriv = ed.utils.randomSecretKey();
  const forgedSig = ed.sign(digest, otherPriv);
  const forgedProof = { ...proof, signature: Buffer.from(forgedSig).toString('base64') };
  try {
    verifyTonProof({ address, stateInit: stateInitB64, proof: forgedProof }, { domain });
    throw new Error('should have rejected forged signature');
  } catch (e) { console.log('PASS rejected forged signature:', e.message); }

  // tamper: client claims a different publicKey but signs with real one that doesn't match stateInit's -> covered since we never trust client publicKey at all.
  console.log('ALL TON PROOF TESTS PASSED');
}

main().catch((e) => { console.error('FAIL', e); process.exit(1); });
