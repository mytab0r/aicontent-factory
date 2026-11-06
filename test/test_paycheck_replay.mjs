/**
 * Replay: реальная mainnet-транзакция USDT-TRC20 (TronGrid JSON, fixture) через
 * tronMatches (матчер счетов paycheck.js) — детерминированный тест, CI-безопасный.
 *
 * Проверяем то, что матчер делает на проде: фильтры (to, contract, confirmed, SUCCESS,
 * окно по block_ts), точное совпадение суммы в микроюнитах закрывает счёт,
 * чужие суммы / до создания счёта / не тот токен — не закрывают.
 *
 * Окно времени: тест не двигает часы, а ставит createdMs счёта в прошлое относительно
 * block_ts фикстуры (created = block_ts - 60s), как это делает create.js на проде.
 */
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const lib = (f) => pathToFileURL(path.resolve(here, '../functions/lib', f)).href;
const { toMicro, tronMatches } = await import(lib('paycheck.js'));
const { PAIRS } = await import(lib('config.js'));

const fixture = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/trc20-mainnet.json'), 'utf8'));
const t = fixture.data[0];
const pair = { ...PAIRS['USDT-TRC20'] };

// --- toMicro: базовые случаи (в т.ч. пыль мельче микроюнита)
assert.strictEqual(toMicro('35769456413459', 6), 35_769_456_413_459n);
assert.strictEqual(toMicro('1000123000000000001', 18), null);

// --- created = block_ts - 60s: перевод попадает в окно счёта
const createdMs = t.block_timestamp - 60_000;

let calls = 0;
const realFetch = globalThis.fetch;
globalThis.fetch = async (url) => {
  calls++;
  assert.ok(String(url).includes('tronscanapi.com'));
  // форма ответа Tronscan = payload тестируемого матчера; фикстура TronGrid приведена к ней
  return new Response(JSON.stringify({
    token_transfers: [{
      transaction_id: t.transaction_id,
      to_address: t.to,
      quant: t.value,
      confirmed: true,
      finalResult: 'SUCCESS',
      block_ts: t.block_timestamp,
      tokenInfo: { tokenId: t.token_info.address, tokenDecimal: t.token_info.decimals },
    }],
  }));
};

try {
  // точная сумма счёта = сумма реального перевода → paid
  const hits = await tronMatches(pair, t.to, t.value, createdMs);
  assert.strictEqual(hits.length, 1, 'ровно одно совпадение');
  assert.strictEqual(hits[0].tx, t.transaction_id);
  assert.strictEqual(hits[0].amount, 35_769_456.413459);

  // чужая сумма не закрывает
  assert.strictEqual((await tronMatches(pair, t.to, '147000000', createdMs)).length, 0);

  // перевод позже окна счёта (tolerance 60s до создания) — не наш
  assert.strictEqual((await tronMatches(pair, t.to, t.value, t.block_timestamp + 61_000)).length, 0);

  // не тот адрес получателя — мимо
  assert.strictEqual((await tronMatches(pair, 'TXotherAddressNotInTheFixture0000', t.value, createdMs)).length, 0);

  // не тот токен (подмена контракта пары)
  assert.strictEqual((await tronMatches({ ...pair, token: 'TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf' }, t.to, t.value, createdMs)).length, 0);

  assert.ok(calls >= 5);
} finally { globalThis.fetch = realFetch; }

console.log('paycheck replay (mainnet fixture): all OK');
