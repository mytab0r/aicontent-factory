/**
 * Конфиг в KV (ключ "config"). Только публичные адреса + включённые пары.
 * Структура:
 * {
 *   "addresses": { "evm": "0x...", "tron": "T...", "solana": "G..." },
 *   "pairs": { "USDT-TRC20": true, "USDT-ERC20": true, "USDT-BEP20": false, ... }
 * }
 * Доступ: CF Access на /admin (настраивается в CF dashboard), Functions только читают.
 */
export const CONFIG_KEY = 'config';

export const PAIRS = {
  'USDT-TRC20': { chain: 'tron', asset: 'USDT', label: 'USDT (Tron TRC20)' },
  'USDT-ERC20': { chain: 'eth', asset: 'USDT', label: 'USDT (Ethereum ERC20)' },
  'USDT-BEP20': { chain: 'bsc', asset: 'USDT', label: 'USDT (BSC BEP20)' },
  'USDT-POLY': { chain: 'poly', asset: 'USDT', label: 'USDT (Polygon)' },
  'USDT-ARC20': { chain: 'arb', asset: 'USDT', label: 'USDT (Arbitrum)' },
};

export function defaultConfig() {
  return { addresses: {}, pairs: {} };
}

/** Адрес какой цепочки нужен паре; null если пара невалидна/выключена/нет адреса. */
export function pairEndpoint(cfg, pairId) {
  const meta = PAIRS[pairId];
  if (!meta) return null;
  if (!cfg.pairs || cfg.pairs[pairId] !== true) return null;
  const addr = (cfg.addresses || {})[meta.chain === 'tron' ? 'tron' : 'evm'];
  if (!addr) return null;
  return { address: addr, ...meta };
}

/** Список включённых пар с адресами — для страницы клиента. */
export function enabledPairs(cfg) {
  return Object.keys(PAIRS)
    .filter((id) => pairEndpoint(cfg, id))
    .map((id) => ({ id, ...PAIRS[id], address: pairEndpoint(cfg, id).address }));
}
