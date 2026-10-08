/**
 * GET /api/invoice/<id>          -> инвойс (сумма, статус, включённые пары с адресами)
 * POST /api/invoice/<id>/pay     -> зафиксировать выбор пары
 * GET /api/invoice/<id>/status   -> проверка оплаты по блокчейну
 *
 * Инвойсы в KV: invoice:<id> = { amount, currency, memo, pair, status, createdMs, paid: {...} }
 */
import { CONFIG_KEY, enabledPairs, defaultConfig } from '../../lib/config.js';
import { checkPayment } from '../../lib/paycheck.js';

const INVOICE_TTL = 60 * 60 * 24 * 30; // 30 дней

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

async function getInvoice(env, id) {
  const raw = await env.KV.get('invoice:' + id);
  return raw ? JSON.parse(raw) : null;
}

export async function onRequestGet({ env, params }) {
  const inv = await getInvoice(env, params.id);
  if (!inv) return json({ error: 'not found' }, 404);
  const cfg = JSON.parse((await env.KV.get(CONFIG_KEY)) || JSON.stringify(defaultConfig()));
  return json({ id: params.id, amount: inv.amount, currency: inv.currency, status: inv.status, pairs: enabledPairs(cfg) });
}

/** Клиент выбрал пару: фиксируем её за инвойсом. */
export async function onRequestPost({ env, params, request }) {
  const inv = await getInvoice(env, params.id);
  if (!inv) return json({ error: 'not found' }, 404);
  const body = await request.json().catch(() => ({}));
  const cfg = JSON.parse((await env.KV.get(CONFIG_KEY)) || JSON.stringify(defaultConfig()));
  const pair = enabledPairs(cfg).find((p) => p.id === body.pair);
  if (!pair) return json({ error: 'pair not enabled' }, 400); // приёмка #3: только включённые пары
  if (inv.pair && inv.pair.id !== pair.id && inv.status !== 'pending') {
    return json({ error: 'already paid differently' }, 409);
  }
  inv.pair = pair;
  await env.KV.put('invoice:' + params.id, JSON.stringify(inv), { expirationTtl: INVOICE_TTL });
  return json({ ok: true, pair });
}

/** Проверка оплаты. Повторный вызов после paid — дешёвый, возвращает зафиксированный факт. */
export async function onRequestPut({ env, params }) {
  const inv = await getInvoice(env, params.id);
  if (!inv) return json({ error: 'not found' }, 404);
  if (inv.paid) return json({ status: 'paid', ...inv.paid });
  if (!inv.pair) return json({ error: 'pair not selected' }, 400);
  try {
    const res = await checkPayment(inv.pair.chain, inv.pair.address, inv.amount, inv.createdMs);
    if (res.found) {
      inv.status = 'paid';
      inv.paid = res;
      await env.KV.put('invoice:' + params.id, JSON.stringify(inv), { expirationTtl: INVOICE_TTL });
      return json({ status: 'paid', ...res });
    }
    return json({ status: 'pending' });
  } catch (e) {
    return json({ status: 'error', error: String(e.message || e) }, 502);
  }
}
