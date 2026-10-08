/**
 * GET /i/<id> — страница клиента: сумма, выбор включённой пары, адрес, QR, «только эта сеть».
 */
import { CONFIG_KEY, enabledPairs, defaultConfig } from '../lib/config.js';

const QR_JS = 'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js';

const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const inline = (v) => JSON.stringify(v).replace(/</g, '\\u003c');

export async function onRequestGet({ env, params }) {
  const raw = await env.KV.get('invoice:' + params.id);
  if (!raw) return new Response('Инвойс не найден', { status: 404, headers: { 'content-type': 'text/plain; charset=utf-8' } });
  const inv = JSON.parse(raw);
  const cfg = JSON.parse((await env.KV.get(CONFIG_KEY)) || JSON.stringify(defaultConfig()));
  const pairs = enabledPairs(cfg);
  const html = `<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Оплата ${esc(inv.amount)} ${esc(inv.currency)}</title>
<script src="${QR_JS}"></script>
<style>
 body{font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;padding:16px;background:#0f1115;color:#e6e6e6}
 .card{background:#171a21;border-radius:12px;padding:20px;margin-top:16px}
 .amount{font-size:40px;font-weight:700}
 .pair{display:block;width:100%;margin:8px 0;padding:14px;border:1px solid #2a2f3a;border-radius:10px;background:#1c2029;color:#e6e6e6;font-size:16px;text-align:left;cursor:pointer}
 .pair[aria-pressed=true]{border-color:#4f8cff;background:#203050}
 .warn{color:#ffb84d;font-weight:600;margin:12px 0}
 .addr{font-family:monospace;word-break:break-all;background:#10131a;padding:10px;border-radius:8px}
 button.pay{width:100%;padding:14px;border:0;border-radius:10px;background:#4f8cff;color:#fff;font-size:16px;font-weight:600;cursor:pointer}
 #qr img{margin:12px auto;display:block;filter:invert(1) hue-rotate(180deg)}
 .muted{color:#8a92a3;font-size:13px}
 .ok{color:#3ddc84;font-weight:700}
 .hidden{display:none}
</style></head><body>
<div class="card">
 <div class="muted">Счёт ${esc(params.id)}${inv.memo ? ' · ' + esc(inv.memo) : ''}</div>
 <div class="amount">${esc(inv.amount)} ${esc(inv.currency)}</div>
</div>
<div class="card">
 <h3>Выберите способ оплаты</h3>
 <div id="pairs"></div>
 <div id="details" class="hidden">
  <p class="warn">⚠ Отправляйте ТОЛЬКО ${'${'}net${'}'} — при переводе из другой сети средства будут потеряны.</p>
  <div class="addr" id="addr"></div>
  <div id="qr"></div>
  <button class="pay" id="check">Я оплатил(а) — проверить</button>
  <div id="status" class="muted"></div>
 </div>
</div>
<script>
const PAIRS = ${inline(pairs)};
const INV_ID = ${inline(params.id)};
let sel = null;
const el = (h) => { const d = document.createElement('div'); d.innerHTML = h; return d; };
const box = document.getElementById('pairs');
if (!PAIRS.length) box.appendChild(el('<p class="warn">Способы оплаты ещё не настроены.</p>'));
for (const p of PAIRS) {
  const b = document.createElement('button');
  b.className = 'pair'; b.textContent = p.label; b.setAttribute('aria-pressed', 'false');
  b.onclick = () => select(p, b);
  box.appendChild(b);
}
function select(p, btn) {
  sel = p;
  for (const b of box.children) b.setAttribute('aria-pressed', String(b === btn));
  document.getElementById('details').classList.remove('hidden');
  document.querySelector('.warn').firstChild.textContent = '⚠ Отправляйте ТОЛЬКО ' + p.asset + ' в сети ' + p.label.split('(')[1].replace(')','') + ' — ';
  document.getElementById('addr').textContent = p.address;
  document.getElementById('qr').innerHTML = '';
  const qr = qrcode(0, 'M'); qr.addData(p.address); qr.make();
  document.getElementById('qr').innerHTML = qr.createImgTag(4, 8);
  fetch('/api/invoice/' + INV_ID, { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify({ pair: p.id }) });
}
document.getElementById('check').onclick = async () => {
  if (!sel) return;
  const st = document.getElementById('status');
  st.textContent = 'Проверяем блокчейн…';
  const r = await fetch('/api/invoice/' + INV_ID, { method: 'PUT' });
  const j = await r.json();
  if (j.status === 'paid') { st.className = 'ok'; st.textContent = '✅ Оплата найдена: ' + j.amount + ' USDT, tx ' + j.tx; }
  else if (j.status === 'pending') st.textContent = 'Пока не найдено. Перевод может занять ~1 минуту — проверьте ещё раз.';
  else st.textContent = 'Ошибка: ' + (j.error || 'неизвестная');
};
</script>
</body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}
