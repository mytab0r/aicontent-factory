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
  // Уникальная сумма: база в центах + случайный хвост 1..999 микроюнитов (6 знаков).
  // Клиент платит ровно её, проверка — точное совпадение (чужой перевод счёт не закроет).
  // Хвост резервируется ключом due:<dueMicro>: два pending-счёта с одной суммой
  // закрывались бы одним переводом. get+put не атомарны (KV), гонка параллельных
  // create в одну мс возможна, но не 1/999 на каждый счёт.
  // ponytail: 999 хвостов на одну базовую сумму за INVOICE_TTL (30 дн); упрёмся — 503,
  // тогда расширить хвост до 4-5 знаков или освобождать due: при оплате/истечении.
  let dueMicro = 0;
  for (let i = 0; i < 20 && !dueMicro; i++) {
    const tail = 1 + (crypto.getRandomValues(new Uint16Array(1))[0] % 999);
    const cand = Math.round(amount * 100) * 10_000 + tail;
    if ((await env.KV.get('due:' + cand)) === null) dueMicro = cand;
  }
  if (!dueMicro) return json({ error: 'no free amount tail, retry later' }, 503);
  await env.KV.put('due:' + dueMicro, id, { expirationTtl: INVOICE_TTL });
  const inv = {
    amount: (dueMicro / 1e6).toFixed(6),
    dueMicro: String(dueMicro),
    currency: typeof body.currency === 'string' ? body.currency.slice(0, 8) : 'USD',
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
