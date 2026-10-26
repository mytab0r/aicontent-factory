/** 500 счетов одной суммы через create.js с заглушкой KV: 0 дублей dueMicro; переполнение -> 503. */
import assert from 'node:assert';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const { onRequestPost } = await import(pathToFileURL(path.resolve(here, '../functions/api/invoice/create.js')).href);

const store = new Map();
const KV = {
  async get(k) { return store.has(k) ? store.get(k) : null; },
  async put(k, v) { store.set(k, v); },
};
const create = (amount) => onRequestPost({
  env: { KV },
  request: new Request('http://x/api/invoice', { method: 'POST', body: JSON.stringify({ amount }) }),
});

const dues = [];
for (let i = 0; i < 500; i++) {
  const r = await create(49);
  assert.strictEqual(r.status, 200);
  const { id } = await r.json();
  dues.push(JSON.parse(store.get('invoice:' + id)).dueMicro);
}
assert.strictEqual(new Set(dues).size, 500, 'duplicate dueMicro');

// все 999 хвостов суммы 7 заняты -> 503, а не дубль
for (let t = 1; t <= 999; t++) store.set('due:' + (700 * 10_000 + t), 'x');
assert.strictEqual((await create(7)).status, 503);
console.log('test_invoice_unique OK: 500 unique, full -> 503');
