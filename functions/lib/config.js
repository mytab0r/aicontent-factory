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

// token + decimals сверены eth_call decimals() на publicnode 2026-10-08 (BSC USDT = 18!).
// Base: нативного USDT нет, берём Circle USDC (6 dec).
export const PAIRS = {
  'USDT-TRC20': { chain: 'tron', asset: 'USDT', label: 'USDT (Tron TRC20)', token: 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', decimals: 6 },
  'USDT-ERC20': { chain: 'eth', asset: 'USDT', label: 'USDT (Ethereum ERC20)', token: '0xdAC17F958D2ee523a2206206994597C13D831ec7', decimals: 6 },
  'USDT-BEP20': { chain: 'bsc', asset: 'USDT', label: 'USDT (BSC BEP20)', token: '0x55d398326f99059fF775485246999027B3197955', decimals: 18 },
  'USDT-POLY': { chain: 'poly', asset: 'USDT', label: 'USDT (Polygon)', token: '0xc2132D05D31c914a87C6611C10748AEb04B58e8F', decimals: 6 },
  'USDT-ARC20': { chain: 'arb', asset: 'USDT', label: 'USDT (Arbitrum)', token: '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9', decimals: 6 },
  'USDC-BASE': { chain: 'base', asset: 'USDC', label: 'USDC (Base)', token: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', decimals: 6 },
};

// Address shapes: trust boundary for owner-entered values (PUT /api/admin/config).
const ADDRESS_VALIDATORS = {
  btc: (v) => /^(bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$/.test(v),
  ton: (v) => /^[EU]Q[A-Za-z0-9_-]{46}$/.test(v),
  tron: (v) => /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(v),
  solana: (v) => /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(v),
  evm: (v) => /^0x[0-9a-fA-F]{40}$/.test(v),
};

export function validAddress(chain, v) {
  return typeof v === 'string' && !!ADDRESS_VALIDATORS[chain] && ADDRESS_VALIDATORS[chain](v);
}

export function defaultConfig() {
  return { addresses: {}, pairs: {} };
}

/**
 * Переопределение контракта пары через окружение (тесты / Nile): PAY_PAIR_<ID>_TOKEN.
 * На проде env-переменных нет -> возвращается mainnet-контракт из PAIRS, поведение не меняется.
 */
export function pairToken(pairId) {
  const ov = globalThis.PAY_PAIR_TOKEN_ENV && globalThis.PAY_PAIR_TOKEN_ENV(pairId);
  return ov || PAIRS[pairId]?.token;
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
