/**
 * Проверка оплаты по блокчейну, только чтение, публичные API (аналог autopilot/crypto.py).
 *
 * Сумма счёта уникальна (create.js добавляет случайный хвост 1..999 микроюнитов), поэтому
 * сравнение ТОЧНОЕ в 6-знаковых микроюнитах: чужой перевод на другую сумму счёт не закрывает.
 * Повторное использование tx отсекает вызывающий (KV paidtx:<chain>:<tx>), здесь — все совпадения.
 *
 * TRON: Tronscan token_trc20/transfers. EVM: eth_getLogs Transfer(to=адрес) на publicnode.com.
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

export async function tronMatches(pair, address, dueMicro, createdMs) {
  const url =
    'https://apilist.tronscanapi.com/api/token_trc20/transfers?limit=50&start=0&sort=-timestamp' +
    '&relatedAddress=' + encodeURIComponent(address) +
    '&filterToken=' + pair.token;
  const r = await fetch(url, { headers: { 'User-Agent': 'pay.pxbt.app' } });
  if (!r.ok) throw new Error('tronscan ' + r.status);
  const j = await r.json();
  const out = [];
  for (const t of j.token_transfers || []) {
    if (t.to_address !== address) continue;
    if (t.tokenInfo?.tokenId !== pair.token) continue;
    if (t.confirmed !== true || t.finalResult !== 'SUCCESS') continue;
    if ((t.block_ts || 0) < createdMs - 60_000) continue; // до создания счёта — не наш платёж
    const micro = toMicro(t.quant, t.tokenInfo?.tokenDecimal ?? pair.decimals);
    if (micro === BigInt(dueMicro)) out.push({ tx: t.transaction_id, amount: Number(micro) / 1e6 });
  }
  return out;
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
