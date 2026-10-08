/**
 * POST /api/invoice  { amount, currency?, memo? }  -> создать инвойс (для owner/бота)
 * Возврат: { id, url } — ссылка /i/<id>.
 */
const INVOICE_TTL = 60 * 60 * 24 * 30;

export async function onRequestPost({ env, request }) {
  const body = await request.json().catch(() => ({}));
  const amount = Number(body.amount);
  if (!isFinite(amount) || amount <= 0 || amount > 1e9) return json({ error: 'bad amount' }, 400);
  const id = crypto.randomUUID().replace(/-/g, '').slice(0, 12);
  const inv = {
    amount,
    currency: typeof body.currency === 'string' ? body.currency.slice(0, 8) : 'USDT',
    memo: typeof body.memo === 'string' ? body.memo.slice(0, 200) : '',
    status: 'pending',
    createdMs: Date.now(),
  };
  await env.KV.put('invoice:' + id, JSON.stringify(inv), { expirationTtl: INVOICE_TTL });
  return json({ id, url: '/i/' + id });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}
