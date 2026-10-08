/**
 * POST /api/claim/nonce  { chain } -> { message, nonce }
 * Одноразовый nonce (5 минут) для подписи владелецем в /admin.
 */
export async function onRequestPost({ env, request }) {
  const body = await request.json().catch(() => ({}));
  const chain = body.chain;
  if (!['evm', 'tron', 'solana'].includes(chain)) {
    return json({ error: 'bad chain' }, 400);
  }
  const nonce = crypto.randomUUID().replace(/-/g, '');
  await env.KV.put('claim:' + nonce, JSON.stringify({ chain, ts: Date.now() }), { expirationTtl: 300 });
  return json({ nonce, message: `pay.pxbt.app: claim ${nonce}\nвладелец pxbt.app` });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}
