/**
 * Tarot funnel (t_6c820b8a): IG Reels / TikTok -> /tarot?src=ig -> free 1-card reading (lead)
 * -> deep 3-card reading as USDT invoice ($9) -> /tarot/r/<invoice> unlocks after payment.
 * KV: tarot:reading:<id> = {q, src, ms}; tarot:deep:<inv> = {rid, counted}; tarot:stats = funnel counters.
 * Pure JS (no node:*), same handler style as functions/api/*.
 */
import * as invoiceCreate from '../api/invoice/create.js';

const MAJOR = [
  ['The Fool', 'a fresh start; trust the leap even when the path is not yet visible'],
  ['The Magician', 'you already hold every tool you need; focus your will and act'],
  ['The High Priestess', 'listen to your intuition; the answer is quiet but already inside you'],
  ['The Empress', 'abundance, care and creativity; let things grow at their own pace'],
  ['The Emperor', 'structure and boundaries; take ownership and lead with a steady hand'],
  ['The Hierophant', 'tradition and guidance; a mentor or proven path can help right now'],
  ['The Lovers', 'a meaningful choice of the heart; align with what you truly value'],
  ['The Chariot', 'momentum through discipline; steer opposing forces toward one goal'],
  ['Strength', 'gentle courage; patience and compassion win where force would fail'],
  ['The Hermit', 'step back and reflect; solitude brings the clarity you are seeking'],
  ['Wheel of Fortune', 'a turning point; cycles shift and luck is moving in your favour'],
  ['Justice', 'truth and fairness; your actions return to you, so choose honestly'],
  ['The Hanged Man', 'pause and surrender; a new perspective unlocks what is stuck'],
  ['Death', 'an ending that clears space; release the old so the new can arrive'],
  ['Temperance', 'balance and moderation; blend opposites slowly for a lasting result'],
  ['The Devil', 'attachments and temptation; notice what quietly holds you back'],
  ['The Tower', 'sudden change; what was unstable falls so something truer can rise'],
  ['The Star', 'hope and healing; after the storm, a calm and guiding light appears'],
  ['The Moon', 'uncertainty and dreams; not everything is as it seems, go slowly'],
  ['The Sun', 'joy, success and warmth; a clear yes and a bright period ahead'],
  ['Judgement', 'an awakening; answer the call and forgive yourself for the past'],
  ['The World', 'completion and wholeness; a chapter closes with real achievement'],
];
const SUITS = [
  ['Wands', 'passion, ambition and creative drive'],
  ['Cups', 'love, emotions and relationships'],
  ['Swords', 'thoughts, truth and difficult decisions'],
  ['Pentacles', 'money, work and the material world'],
];
const RANKS = [
  ['Ace', 'a new seed of energy is offered to you'],
  ['Two', 'a choice or partnership asks for balance'],
  ['Three', 'early growth and collaboration bear fruit'],
  ['Four', 'stability, rest and consolidation are needed'],
  ['Five', 'conflict or loss tests your resilience'],
  ['Six', 'harmony returns and help is exchanged'],
  ['Seven', 'perseverance against doubt is required'],
  ['Eight', 'rapid movement and focused effort pay off'],
  ['Nine', 'you are close to fulfilment; hold your ground'],
  ['Ten', 'a cycle reaches its peak, for better or heavier'],
  ['Page', 'curious news or a message arrives'],
  ['Knight', 'bold action pushes things forward fast'],
  ['Queen', 'mature, nurturing mastery guides you'],
  ['King', 'calm authority and control lead the way'],
];

export const DECK = [
  ...MAJOR.map(([name, meaning]) => ({ name, meaning })),
  ...SUITS.flatMap(([s, theme]) => RANKS.map(([r, m]) => ({ name: `${r} of ${s}`, meaning: `${m} in matters of ${theme}` }))),
];

// FNV-1a seed -> mulberry32: deterministic spread per reading id.
function rng(seed) {
  let h = 2166136261;
  for (const c of String(seed)) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {
    h = (h + 0x6d2b79f5) | 0;
    let t = Math.imul(h ^ (h >>> 15), 1 | h);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export function draw(seed, n) {
  const r = rng(seed), idx = DECK.map((_, i) => i);
  for (let i = 0; i < n; i++) { const j = i + Math.floor(r() * (idx.length - i)); [idx[i], idx[j]] = [idx[j], idx[i]]; }
  return idx.slice(0, n).map((i) => DECK[i]);
}

export const PRICE = 9;
const SOURCES = ['ig', 'tiktok', 'yt', 'tg'];
const TTL = 60 * 60 * 24 * 30;
const bucket = (s) => (SOURCES.includes(s) ? s : 'other');
const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
const html = (h, status = 200) => new Response(h, { status, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
const newId = () => crypto.randomUUID().replace(/-/g, '').slice(0, 12);

async function bump(env, field, src) {
  // ponytail: get+put не атомарны в CF KV; в контейнере (FileKV, один процесс) гонки нет.
  const st = JSON.parse((await env.KV.get('tarot:stats')) || '{"visits":{},"leads":{},"checkouts":0,"paid":0}');
  if (src) st[field][src] = (st[field][src] || 0) + 1; else st[field] += 1;
  await env.KV.put('tarot:stats', JSON.stringify(st));
}

const STYLE = `<style>body{font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:16px;background:#120d1f;color:#eee}
.card{background:#1e1633;border-radius:14px;padding:20px;margin-top:16px}h1{font-size:24px}
textarea,button{width:100%;box-sizing:border-box;border-radius:10px;font-size:16px;padding:12px;margin-top:8px}
button{background:#b48cff;border:0;color:#120d1f;font-weight:700;cursor:pointer}.muted{color:#a89cc4;font-size:13px}.hidden{display:none}</style>`;
const page = (title, body) => `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title>${STYLE}</head><body>${body}</body></html>`;

/** GET /tarot?src=ig — landing, counts the visit. */
export async function landing({ env, request }) {
  const src = bucket(new URL(request.url).searchParams.get('src'));
  await bump(env, 'visits', src);
  return html(page('Free Tarot Reading', `<div class="card"><h1>Your free tarot reading</h1>
<p>Ask one question and draw a card. The first reading is free.</p>
<textarea id="q" rows="3" maxlength="300" placeholder="What do you want to know?"></textarea>
<button id="go">Draw my free card</button></div>
<div class="card hidden" id="res"><h2 id="name"></h2><p id="meaning"></p>
<p>Want the full story? A deep 3-card spread (where you came from, where you are, where it leads) for $${PRICE} in USDT.</p>
<button id="deep">Get my deep reading — $${PRICE}</button><p class="muted" id="msg"></p></div>
<p class="muted">For entertainment and self-reflection. Not medical, legal or financial advice.</p>
<script>
const SRC=${JSON.stringify(src)};let RID=null;const $=(i)=>document.getElementById(i);
$('go').onclick=async()=>{const r=await(await fetch('/api/tarot/reading',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({question:$('q').value,src:SRC})})).json();
RID=r.id;$('name').textContent=r.card.name;$('meaning').textContent=r.card.meaning;$('res').classList.remove('hidden');};
$('deep').onclick=async()=>{const r=await(await fetch('/api/tarot/deep',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id:RID})})).json();
if(!r.pay_url){$('msg').textContent='Something went wrong, try again.';return;}
localStorage.setItem('tarot_reading',r.reading_url);$('msg').innerHTML='After paying, open your reading: <a href="'+r.reading_url+'">'+location.origin+r.reading_url+'</a>';
window.open(r.pay_url,'_blank');};
</script>`));
}

/** POST /api/tarot/reading {question, src} -> free card (= lead). */
export async function reading({ env, request }) {
  const b = await request.json().catch(() => ({}));
  const id = newId(), src = bucket(b.src);
  await env.KV.put('tarot:reading:' + id, JSON.stringify({ q: String(b.question || '').slice(0, 300), src, ms: Date.now() }), { expirationTtl: TTL });
  await bump(env, 'leads', src);
  return json({ id, card: draw(id, 1)[0] });
}

/** POST /api/tarot/deep {id} -> USDT invoice + locked reading url. */
export async function deep({ env, request }) {
  const b = await request.json().catch(() => ({}));
  if (!/^[A-Za-z0-9]{1,64}$/.test(String(b.id || '')) || !(await env.KV.get('tarot:reading:' + b.id))) return json({ error: 'not found' }, 404);
  const req = new Request('http://local/api/invoice', { method: 'POST', body: JSON.stringify({ amount: PRICE, currency: 'USDT', memo: 'Deep tarot reading' }) });
  const inv = await (await invoiceCreate.onRequestPost({ env, request: req })).json();
  await env.KV.put('tarot:deep:' + inv.id, JSON.stringify({ rid: b.id, counted: false }), { expirationTtl: TTL });
  await bump(env, 'checkouts');
  return json({ pay_url: inv.url, reading_url: '/tarot/r/' + inv.id });
}

/** GET /tarot/r/<invoice> — locked until the invoice is paid; first unlocked view counts as paid. */
export async function paidReading({ env, params }) {
  const d = JSON.parse((await env.KV.get('tarot:deep:' + params.id)) || 'null');
  const inv = JSON.parse((await env.KV.get('invoice:' + params.id)) || 'null');
  if (!d || !inv) return html(page('Not found', '<div class="card">Reading not found.</div>'), 404);
  if (inv.status !== 'paid') {
    return html(page('Your deep reading', `<div class="card"><h1>Payment not paid yet</h1><p>Complete the payment, then refresh this page.</p><p><a href="/i/${esc(params.id)}">Open payment page</a></p></div>`));
  }
  if (!d.counted) { d.counted = true; await env.KV.put('tarot:deep:' + params.id, JSON.stringify(d), { expirationTtl: TTL }); await bump(env, 'paid'); }
  const r = JSON.parse((await env.KV.get('tarot:reading:' + d.rid)) || '{}');
  const cards = draw(d.rid + ':deep', 3);
  const rows = ['Past', 'Present', 'Future'].map((pos, i) => `<div class="card"><div class="muted">${pos}</div><h2>${esc(cards[i].name)}</h2><p>${esc(cards[i].meaning)}</p></div>`).join('');
  return html(page('Your deep reading', `<div class="card"><h1>Your deep reading</h1>${r.q ? `<p class="muted">Question: ${esc(r.q)}</p>` : ''}</div>${rows}`));
}

export async function stats({ env }) {
  return json(JSON.parse((await env.KV.get('tarot:stats')) || '{"visits":{},"leads":{},"checkouts":0,"paid":0}'));
}
