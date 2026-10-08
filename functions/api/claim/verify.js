/**
 * POST /api/claim/verify  { chain, address, signature, nonce }
 * Проверяет подпись + свежий nonce, сохраняет адрес в конфиг KV.
 * Без валидной подписи адрес НЕ сохраняется (acceptance #2).
 */
import { verifyWalletSignature, normalizeAddress } from '../../lib/wallet-verify.js';
import { CONFIG_KEY, PAIRS } from '../../lib/config.js';

export async function onRequestPost({ env, request }) {
  const body = await request.json().catch(() => ({}));
  const { chain, address, signature, nonce } = body;
  if (!chain || !address || !signature || !nonce) return json({ ok: false, error: 'missing fields' }, 400);

  const nonceKey = 'claim:' + nonce;
  const raw = await env.KV.get(nonceKey);
  if (!raw) return json({ ok: false, error: 'nonce expired or unknown' }, 400);
  const { chain: nonceChain } = JSON.parse(raw);
  if (nonceChain !== chain) return json({ ok: false, error: 'chain mismatch' }, 400);

  const message = `pay.pxbt.app: claim ${nonce}\nвладелец pxbt.app`;
  try {
    const res = verifyWalletSignature({ chain, message, signature, address });
    // Одноразовость: nonce сжигается ТОЛЬКО после успеха (не даёт DoS-сжигание чужих nonce)
    await env.KV.delete(nonceKey);

    const cfg = JSON.parse((await env.KV.get(CONFIG_KEY)) || '{"addresses":{},"pairs":{}}');
    const stored = normalizeAddress(chain, res.address);
    const addrKey = chain === 'tron' ? 'tron' : chain === 'solana' ? 'solana' : 'evm';
    cfg.addresses[addrKey] = stored;
    await env.KV.put(CONFIG_KEY, JSON.stringify(cfg));
    return json({ ok: true, address: stored, chain });
  } catch (e) {
    return json({ ok: false, error: 'signature verification failed', detail: String(e.message || e) }, 400);
  }
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}
