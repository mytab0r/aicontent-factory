/**
 * Проверка оплаты по блокчейну, только чтение, публичные API (аналог autopilot/crypto.py).
 *
 * TRON (USDT-TRC20): Tronscan token_trc20/transfers — входящие переводы на адрес,
 *   фильтр по контракту USDT, сумма из quant (6 dec), подтверждённые SUCCESS.
 * EVM (USDT ERC20/BEP20/Polygon/Arbitrum): публичный RPC publicnode.com,
 *   eth_getLogs Transfer(to=адрес), окно поиска от invoice
 *   (created_at → номер блока приблизительно), сумма из data (6 dec).
 *
 * Возврат: { found: bool, amount: number, tx: string } | { found: false }.
 */
const USDT_CONTRACTS = {
  tron: 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
  eth: '0xdAC17F958D2ee523a2206206994597C13D831ec7',
  bsc: '0x55d398326f99059fF775485246999027B3197955',
  poly: '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
  arb: '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9',
};
const RPC = {
  eth: 'https://ethereum-rpc.publicnode.com',
  bsc: 'https://bsc-rpc.publicnode.com',
  poly: 'https://polygon-bor-rpc.publicnode.com',
  arb: 'https://arbitrum-one-rpc.publicnode.com',
};
// среднее время блока в секундах — для оценки стартового блока от времени invoice
const BLOCK_TIME = { eth: 12, bsc: 3, poly: 2, arb: 1 };
const TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef';

function amountMatches(quantRaw, decimals, expectedAmount) {
  // Сравнение в целых минорных юнитах, чтобы не ловить float-погрешность
  const expectedMinor = BigInt(Math.round(expectedAmount * 10 ** decimals));
  return BigInt(quantRaw) >= expectedMinor;
}

async function tronPaid(address, expectedAmount, createdMs) {
  const url =
    'https://apilist.tronscanapi.com/api/token_trc20/transfers?limit=50&start=0&sort=-timestamp' +
    '&relatedAddress=' + encodeURIComponent(address) +
    '&filterToken=' + USDT_CONTRACTS.tron;
  const r = await fetch(url, { headers: { 'User-Agent': 'pay.pxbt.app' } });
  if (!r.ok) throw new Error('tronscan ' + r.status);
  const j = await r.json();
  for (const t of j.token_transfers || []) {
    if (t.to_address !== address) continue;
    if (t.tokenInfo?.tokenId !== USDT_CONTRACTS.tron) continue;
    if (t.confirmed !== true || t.finalResult !== 'SUCCESS') continue;
    if ((t.block_ts || 0) < createdMs - 60_000) continue; // до создания счёта — не наш платёж
    const dec = t.tokenInfo?.tokenDecimal ?? 6;
    if (amountMatches(t.quant, dec, expectedAmount)) {
      return { found: true, amount: Number(BigInt(t.quant)) / 10 ** dec, tx: t.transaction_id };
    }
  }
  return { found: false };
}

async function evmPaid(chain, address, expectedAmount, createdSec) {
  const rpc = RPC[chain];
  const bh = await rpcCall(rpc, 'eth_blockNumber', []);
  const tip = parseInt(bh, 16);
  const approxStart = tip - Math.floor((Date.now() / 1000 - createdSec) / BLOCK_TIME[chain]) - 60;
  const fromBlock = '0x' + Math.max(approxStart, 0).toString(16);
  const pad = (a) => a.replace(/^0x/, '').toLowerCase().padStart(64, '0');
  const logs = await rpcCall(rpc, 'eth_getLogs', [
    {
      fromBlock,
      toBlock: 'latest',
      address: USDT_CONTRACTS[chain],
      topics: [TRANSFER_TOPIC, null, '0x' + pad(address)],
    },
  ]);
  for (const log of logs) {
    // USDT на всех этих чейнах: 6 decimals
    const quant = BigInt(log.data).toString();
    if (amountMatches(quant, 6, expectedAmount)) {
      return { found: true, amount: Number(BigInt(quant)) / 1e6, tx: log.transactionHash };
    }
  }
  return { found: false };
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

/** Проверить оплату пары. createdMs — ms создания счёта. */
export async function checkPayment(chain, address, expectedAmount, createdMs) {
  if (chain === 'tron') return tronPaid(address, expectedAmount, createdMs);
  if (RPC[chain]) return evmPaid(chain, address, expectedAmount, Math.floor(createdMs / 1000));
  throw new Error('unknown chain: ' + chain);
}
