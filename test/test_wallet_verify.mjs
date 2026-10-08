import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyWalletSignature, normalizeAddress } from '../functions/lib/wallet-verify.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'vectors.json'), 'utf8'));
const MSG = V.msg;

// Позитивные кейсы: адрес восстанавливается из подписи / проверяется
assert.strictEqual(verifyWalletSignature({ chain: 'evm', message: MSG, signature: V.evm.sig, address: V.evm.addr }).address, V.evm.addr, 'EVM recovery');
assert.strictEqual(verifyWalletSignature({ chain: 'tron', message: MSG, signature: V.tron.sig, address: V.tron.addr }).address, V.tron.addr, 'TRON recovery');
assert.strictEqual(verifyWalletSignature({ chain: 'solana', message: MSG, signature: V.solana.sig, address: V.solana.addr }).address, V.solana.addr, 'SOL verify');

// Неверная подпись -> отказ (адрес не совпадает)
assert.throws(() => verifyWalletSignature({ chain: 'evm', message: MSG + 'x', signature: V.evm.sig, address: V.evm.addr }), 'EVM wrong msg must fail');
assert.throws(() => verifyWalletSignature({ chain: 'tron', message: MSG + 'x', signature: V.tron.sig, address: V.tron.addr }), 'TRON wrong msg must fail');
assert.throws(() => verifyWalletSignature({ chain: 'solana', message: MSG, signature: V.solana.sig, address: V.solana.addr.slice(0, -2) + 'zz' }), 'SOL wrong addr must fail');

// Чужой адрес при верной подписи -> отказ
assert.throws(() => verifyWalletSignature({ chain: 'evm', message: MSG, signature: V.evm.sig, address: '0x0000000000000000000000000000000000000000' }), 'EVM address mismatch must fail');
assert.throws(() => verifyWalletSignature({ chain: 'tron', message: MSG, signature: V.tron.sig, address: 'TXXXXXX' }), 'TRON address mismatch must fail');

// Подмена v/мусор в подписи
assert.throws(() => verifyWalletSignature({ chain: 'evm', message: MSG, signature: V.evm.sig.slice(0, -2) + 'ff' }), 'EVM bad v must fail');
assert.throws(() => verifyWalletSignature({ chain: 'tron', message: MSG, signature: '0x00' + V.tron.sig.slice(4) }), 'TRON bad recovery must fail');

// Сообщение не от нашего сервера -> отказ (replay чужого сообщения)
assert.throws(() => verifyWalletSignature({ chain: 'evm', message: 'random site msg', signature: V.evm.sig }), 'foreign message must fail');

// Нормализация
assert.strictEqual(normalizeAddress('evm', '0xABCdef'), '0xabcdef');
assert.strictEqual(normalizeAddress('tron', 'TCvZ'), 'TCvZ');

console.log('wallet-verify: all OK');
