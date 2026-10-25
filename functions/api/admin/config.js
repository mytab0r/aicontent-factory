/**
 * GET  /api/admin/config  -> текущий конфиг (адреса + пары)
 * PUT  /api/admin/config  { pairs: { "USDT-TRC20": true, ... } } -> обновить галочки пар
 * Доступ: CF Access на /admin (проверяется на уровне CF; здесь — только поддомен admin).
 * Секретов в ответе нет: конфиг хранит только публичные адреса.
 */
import { CONFIG_KEY, PAIRS, validAddress, defaultConfig } from '../../lib/config.js';

export async function onRequestGet({ env }) {
  const cfg = JSON.parse((await env.KV.get(CONFIG_KEY)) || JSON.stringify(defaultConfig()));
  return json({ addresses: cfg.addresses || {}, pairs: cfg.pairs || {}, knownPairs: PAIRS });
}

export async function onRequestPut({ env, request }) {
  const body = await request.json().catch(() => ({}));
  const hasPairs = body && typeof body.pairs === 'object';
  const hasAddresses = body && typeof body.addresses === 'object' && !Array.isArray(body.addresses);
  if (!hasPairs && !hasAddresses) return json({ error: 'pairs or addresses object required' }, 400);
  const cfg = JSON.parse((await env.KV.get(CONFIG_KEY)) || JSON.stringify(defaultConfig()));
  if (hasAddresses) {
    for (const [chain, v] of Object.entries(body.addresses)) {
      if (!validAddress(chain, v)) return json({ error: `bad ${chain} address` }, 400);
      cfg.addresses[chain] = v.trim();
    }
  }
  if (hasPairs) for (const [id, on] of Object.entries(body.pairs)) {
    if (!(id in PAIRS)) return json({ error: 'unknown pair ' + id }, 400);
    cfg.pairs[id] = on === true;
  }
  await env.KV.put(CONFIG_KEY, JSON.stringify(cfg));
  return json({ ok: true, pairs: cfg.pairs });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}
