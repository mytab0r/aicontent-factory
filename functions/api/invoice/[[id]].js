/**
 * GET /api/invoice/<id>          -> инвойс (сумма, статус, включённые пары с адресами)
 * POST /api/invoice/<id>/pay     -> зафиксировать выбор пары
 * GET /api/invoice/<id>/status   -> проверка оплаты по блокчейну
 *
 * Инвойсы в KV: invoice:<id> = { amount, dueMicro, currency, memo, pair, status, createdMs, paid: {...} }
 * Реестр tx: paidtx:<chain>:<tx> = <invoice id> — один перевод закрывает только один счёт.
 */
import { CONFIG_KEY, PAIRS, enabledPairs, pairToken, defaultConfig } from '../../lib/config.js';
import { findPayments } from '../../lib/paycheck.js';

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
    const token = pairToken(inv.pair.id);
    const pair = { ...PAIRS[inv.pair.id], token, address: inv.pair.address };
    for (const m of await findPayments(pair, pair.address, inv.dueMicro, inv.createdMs)) {
      // ponytail: get+put не атомарны в CF KV; в контейнере (FileKV, один процесс) гонки нет.
      const key = `paidtx:${pair.chain}:${m.tx}`;
      const owner = await env.KV.get(key);
      if (owner && owner !== params.id) continue; // tx уже закрыл другой счёт
      await env.KV.put(key, params.id);
      inv.status = 'paid';
      inv.paid = { found: true, ...m };
      await env.KV.put('invoice:' + params.id, JSON.stringify(inv), { expirationTtl: INVOICE_TTL });
      return json({ status: 'paid', ...inv.paid });
    }
    return json({ status: 'pending' });
  } catch (e) {
    return json({ status: 'error', error: String(e.message || e) }, 502);
  }
}
