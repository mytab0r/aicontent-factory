/**
 * Tarot funnel on pay.pxbt.app (t_6c820b8a): IG/TikTok -> /tarot?src=ig -> free 1-card reading (lead)
 * -> deep 3-card reading as USDT invoice -> /tarot/r/<invoice> unlocks after payment. Funnel counters for the digest.
 * Run: node test/test_tarot.mjs
 */
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { makeServer } from '../deploy/pay-page/server.mjs';
import { DECK, draw } from '../functions/tarot/index.js';

assert.strictEqual(DECK.length, 78, 'full deck');
assert.strictEqual(new Set(DECK.map((c) => c.name)).size, 78, 'unique cards');
assert.ok(DECK.every((c) => c.meaning.length > 20), 'every card has a meaning');
assert.deepStrictEqual(draw('seed-a', 3), draw('seed-a', 3), 'deterministic per seed');
assert.strictEqual(new Set(draw('seed-b', 3).map((c) => c.name)).size, 3, 'no duplicate cards in a spread');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tarot-'));
const srv = makeServer({ dataDir: dir, apiToken: 'tok123' });
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const base = 'http://127.0.0.1:' + srv.address().port;
const req = (p, init = {}) => fetch(base + p, init);
const post = (p, body) => req(p, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

try {
  // landing: English, public, counts the visit by source
  const page = await req('/tarot?src=ig');
  assert.strictEqual(page.status, 200);
  const html = await page.text();
  assert.match(html, /lang="en"/);
  assert.match(html, /free/i);

  // free reading = lead
  let r = await post('/api/tarot/reading', { question: 'Will I find love?', src: 'ig' });
  assert.strictEqual(r.status, 200);
  const free = await r.json();
  assert.ok(free.id && free.card.name && free.card.meaning, 'free card returned');
  assert.strictEqual((await post('/api/tarot/reading', { question: 'x'.repeat(5000), src: '<script>' })).status, 200, 'junk input tolerated');

  // upsell: deep reading -> real invoice (amount > 0, so create.js accepts it)
  r = await post('/api/tarot/deep', { id: free.id });
  assert.strictEqual(r.status, 200);
  const deep = await r.json();
  assert.match(deep.pay_url, /^\/i\/[A-Za-z0-9]+$/);
  assert.match(deep.reading_url, /^\/tarot\/r\/[A-Za-z0-9]+$/);
  const inv = await (await req('/api/invoice/' + deep.pay_url.slice(3))).json();
  assert.ok(Number(inv.amount) >= 9 && Number(inv.amount) < 10, 'priced invoice, unique tail');
  assert.strictEqual((await post('/api/tarot/deep', { id: 'nope' })).status, 404, 'unknown reading');

  // locked until paid, no deep cards leaked
  let rp = await (await req(deep.reading_url)).text();
  assert.match(rp, /not paid yet/i);
  assert.ok(!rp.includes('Past'), 'spread hidden before payment');

  // mark paid (as invoice PUT would after on-chain match) -> unlocked, counted once
  const kvFile = path.join(dir, 'kv.json');
  const kv = JSON.parse(fs.readFileSync(kvFile, 'utf8'));
  const key = 'invoice:' + deep.pay_url.slice(3);
  const v = JSON.parse(kv[key].v); v.status = 'paid'; kv[key].v = JSON.stringify(v);
  fs.writeFileSync(kvFile, JSON.stringify(kv));
  srv.reloadKV();
  rp = await (await req(deep.reading_url)).text();
  assert.match(rp, /Past/); assert.match(rp, /Future/);
  await req(deep.reading_url);

  // stats: token only; funnel numbers for the digest
  assert.strictEqual((await req('/api/tarot/stats')).status, 403);
  assert.strictEqual((await req('/api/tarot/stats', { headers: { authorization: 'Bearer bad' } })).status, 403);
  const st = await (await req('/api/tarot/stats', { headers: { authorization: 'Bearer tok123' } })).json();
  assert.strictEqual(st.visits.ig, 1);
  assert.strictEqual(st.leads.ig, 1);
  assert.strictEqual(st.leads.other, 1, 'unknown src bucketed, not stored raw');
  assert.strictEqual(st.checkouts, 1);
  assert.strictEqual(st.paid, 1, 'paid counted once');
  console.log('test_tarot OK');
} finally {
  srv.close();
}
