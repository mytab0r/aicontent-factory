/**
 * Проверка оплаты по блокчейну, только чтение, публичные API (аналог autopilot/crypto.py).
 *
 * Сумма счёта уникальна (create.js добавляет случайный хвост 1..999 микроюнитов), поэтому
 * сравнение ТОЧНОЕ в 6-знаковых микроюнитах: чужой перевод на другую сумму счёт не закрывает.
 * Повторное использование tx отсекает вызывающий (KV paidtx:<chain>:<tx>), здесь — все совпадения.
 *
 * TRON: TronGrid v1 trc20 transfers (env TRON_API, по умолчанию mainnet). EVM: eth_getLogs Transfer(to=адрес) на publicnode.com.
 * Возврат: [{ tx, amount }] — подходящие переводы, новые сверху.
 */
const RPC = {
  eth: 'https://ethereum-rpc.publicnode.com',
  bsc: 'https://bsc-rpc.publicnode.com',
  poly: 'https://polygon-bor-rpc.publicnode.com',
  arb: 'https://arbitrum-one-rpc.publicnode.com',
  base: 'https://base-rpc.publicnode.com',
};
// среднее время блока в секундах — для оценки стартового блока от времени invoice
const BLOCK_TIME = { eth: 12, bsc: 3, poly: 2, arb: 1, base: 2 };
const TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef';

/** Сырое количество токена -> микроюниты (6 знаков); null если есть «пыль» мельче микроюнита. */
export function toMicro(quantRaw, decimals) {
  const q = BigInt(quantRaw);
  if (decimals === 6) return q;
  if (decimals > 6) {
    const k = 10n ** BigInt(decimals - 6);
    return q % k === 0n ? q / k : null;
  }
  return q * 10n ** BigInt(6 - decimals);
}

// TronGrid v1: официальный API Tron, тот же формат на mainnet и Nile (база — env TRON_API).
// only_confirmed=true: в выдаче только подтверждённые; TRC20 Transfer эмитится лишь успешной tx.
const TRON_API = () => (globalThis.process?.env?.TRON_API || 'https://api.trongrid.io').replace(/\/+$/, '');

/** Чистый матчер по ответу TronGrid /v1/accounts/<a>/transactions/trc20 (для replay-теста). */
export function tronMatchesFromTronGrid(j, pair, address, dueMicro, createdMs) {
  const out = [];
  for (const t of j.data || []) {
    if (t.to !== address || t.type !== 'Transfer') continue;
    if (t.token_info?.address !== pair.token) continue;
    if ((t.block_timestamp || 0) < createdMs - 60_000) continue; // до создания счёта — не наш платёж
    const micro = toMicro(t.value, t.token_info?.decimals ?? pair.decimals);
    if (micro === BigInt(dueMicro)) out.push({ tx: t.transaction_id, amount: Number(micro) / 1e6 });
  }
  return out;
}

async function tronMatches(pair, address, dueMicro, createdMs) {
  const url =
    TRON_API() + '/v1/accounts/' + encodeURIComponent(address) + '/transactions/trc20' +
    '?limit=50&only_to=true&only_confirmed=true&order_by=block_timestamp,desc' +
    '&contract_address=' + pair.token + '&min_timestamp=' + Math.max(createdMs - 60_000, 0);
  const r = await fetch(url, { headers: { 'User-Agent': 'pay.pxbt.app' } });
  if (!r.ok) throw new Error('trongrid ' + r.status);
  return tronMatchesFromTronGrid(await r.json(), pair, address, dueMicro, createdMs);
}

async function evmMatches(pair, address, dueMicro, createdSec) {
  const rpc = RPC[pair.chain];
  const tip = parseInt(await rpcCall(rpc, 'eth_blockNumber', []), 16);
  const approxStart = tip - Math.floor((Date.now() / 1000 - createdSec) / BLOCK_TIME[pair.chain]) - 60;
  const pad = (a) => a.replace(/^0x/, '').toLowerCase().padStart(64, '0');
  const logs = await rpcCall(rpc, 'eth_getLogs', [
    { fromBlock: '0x' + Math.max(approxStart, 0).toString(16), toBlock: 'latest', address: pair.token, topics: [TRANSFER_TOPIC, null, '0x' + pad(address)] },
  ]);
  const out = [];
  for (const log of logs.slice().reverse()) {
    const micro = toMicro(BigInt(log.data).toString(), pair.decimals);
    if (micro === BigInt(dueMicro)) out.push({ tx: log.transactionHash, amount: Number(micro) / 1e6 });
  }
  return out;
}

async function rpcCall(rpc, method, params) {
  const r = await fetch(rpc, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  if (!r.ok) throw new Error(rpc + ' ' + r.status);
  const j = await r.json();
  if (j.error) throw new Error(rpc + ': ' + j.error.message);
  return j.result;
}

/** Переводы ровно на dueMicro (6-знаковые микроюниты) на address после createdMs. */
export async function findPayments(pair, address, dueMicro, createdMs) {
  if (pair.chain === 'tron') return tronMatches(pair, address, dueMicro, createdMs);
  if (RPC[pair.chain]) return evmMatches(pair, address, dueMicro, Math.floor(createdMs / 1000));
  throw new Error('unknown chain: ' + pair.chain);
}
