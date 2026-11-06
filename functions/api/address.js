/**
 * GET /api/address?chain=evm|tron|solana -> { chain, address }
 *
 * Единственный источник адреса кошелька владельца для агентов (карточка t_705becfe):
 * читает тот же KV-конфиг `config`, что пишется подписанным claim в /admin.
 * Адреса публичны (показываются клиенту на /i/<id>), поэтому ручка без авторизации.
 * Адреса нет -> 404 с явной ошибкой: агент обязан упасть, а не молча брать дефолт.
 */
import { CONFIG_KEY, defaultConfig } from '../lib/config.js';

export async function onRequestGet({ env, request }) {
  const chain = new URL(request.url).searchParams.get('chain');
  if (!['evm', 'tron', 'solana', 'btc', 'ton'].includes(chain)) return json({ error: 'bad chain, use evm|tron|solana|btc|ton' }, 400);
  const cfg = JSON.parse((await env.KV.get(CONFIG_KEY)) || JSON.stringify(defaultConfig()));
  const address = (cfg.addresses || {})[chain];
  if (!address) return json({ error: `no ${chain} address in registry (owner must claim it at pay.pxbt.app/admin)` }, 404);
  return json({ chain, address });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
}
