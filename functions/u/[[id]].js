/**
 * GET /u/<id> — личная страница оплаты: плательщик выбирает сеть (и монету для EVM), получает адрес и QR.
 * <id> — адрес получателя: EVM 0x…, Tron T…, Solana base58, BTC bc1q, TON. Проверяется существующими
 * валидаторами lib/config.js: новой БД и регистрации нет, id = адрес.
 * Неизвестный/битый id -> HTML 404 (не пустой экран, не 500).
 * Сети и монеты — из существующих NETWORKS + EVM_TOKENS (functions/pay/index.js), не хардкод здесь.
 */
import { validAddress } from '../lib/config.js';
import { NETWORKS, EVM_TOKENS } from '../pay/index.js';

const QR_JS = 'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js';
// Формы адресов разных цепочек не пересекаются, порядок — только для читаемости.
const CHAINS = ['tron', 'btc', 'ton', 'solana', 'evm'];

const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const inline = (v) => JSON.stringify(v).replace(/</g, '\\u003c');
const BASE_CSS = `body{font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;padding:16px;background:#0f1115;color:#e6e6e6}
 .card{background:#171a21;border-radius:12px;padding:20px;margin-top:16px}
 .muted{color:#8a92a3;font-size:13px} h1{font-size:20px;margin:0 0 6px} a{color:#4f8cff}`;

/** Сети для адреса этой цепочки: EVM-адрес один на все EVM-сети, остальные работают только в своей. */
export function networksFor(chain) {
  const out = [];
  for (const n of NETWORKS) {
    if (chain === 'evm') {
      if (!n.evm) continue;
      const sub = n.id.split(':')[1];
      const tokens = EVM_TOKENS.map((t) => ({ id: t.id, label: t.label, contract: t.contracts[sub] })).filter((t) => t.contract);
      if (tokens.length) out.push({ id: n.id, label: n.label, net: n.net, warn: n.warn, tokens });
    } else if (n.id === chain) out.push({ id: n.id, label: n.label, net: n.net, warn: n.warn });
  }
  return out;
}

export async function onRequestGet({ params }) {
  const id = String((params && params.id) || '');
  const chain = CHAINS.find((c) => validAddress(c, id));
  const nets = chain ? networksFor(chain) : [];
  if (!nets.length) return notFound();
  const short = id.length > 16 ? id.slice(0, 8) + '…' + id.slice(-6) : id;
  const html = `<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Оплата на ${esc(short)}</title>
<script src="${QR_JS}"></scr` + `ipt>
<style>${BASE_CSS}
 .opt{display:block;width:100%;margin:8px 0;padding:14px;border:1px solid #2a2f3a;border-radius:10px;background:#1c2029;color:#e6e6e6;font-size:16px;text-align:left;cursor:pointer}
 .opt[aria-pressed=true]{border-color:#4f8cff;background:#203050}
 .opt small{color:#8a92a3;margin-left:8px}
 .tok{display:inline-block;width:auto;margin:6px 6px 0 0;padding:8px 14px;border:1px solid #2a2f3a;border-radius:8px;background:#1c2029;color:#e6e6e6;font-size:14px;cursor:pointer}
 .tok[aria-pressed=true]{border-color:#4f8cff;background:#203050}
 .warn{color:#ffb84d;font-weight:600;margin:12px 0;overflow-wrap:anywhere}
 .addr{font-family:monospace;word-break:break-all;background:#10131a;padding:10px;border-radius:8px}
 button.act{width:100%;margin-top:10px;padding:12px;border:0;border-radius:10px;background:#4f8cff;color:#fff;font-size:15px;font-weight:600;cursor:pointer}
 #qr img{margin:12px auto;display:block;max-width:100%;filter:invert(1) hue-rotate(180deg)}
 .hidden{display:none}
</style></head><body>
<div class="card"><h1>Оплата</h1>
<div class="muted">Получатель ${esc(short)} · выберите сеть — покажу адрес и QR.</div></div>
<div class="card">
 <div id="opts"></div>
 <div id="details" class="hidden">
  <div id="toks"></div>
  <p class="warn"></p>
  <div class="addr" id="addr"></div>
  <div id="qr"></div>
  <button class="act" id="copy">Скопировать адрес</button>
  <div class="muted" id="done" style="margin-top:8px"></div>
 </div>
</div>
<script>
const NETS = ${inline(nets)};
const PAY_TO = ${inline(id)};
const box = document.getElementById('opts');
let sel = null, tok = null;
for (const c of NETS) {
  const b = document.createElement('button');
  b.className = 'opt'; b.setAttribute('aria-pressed', 'false'); b.textContent = c.label;
  if (c.warn) { const s = document.createElement('small'); s.textContent = c.warn; b.appendChild(s); }
  b.onclick = () => show(c, b);
  box.appendChild(b);
}
function show(c, b) {
  for (const x of box.children) x.setAttribute('aria-pressed', String(x === b));
  sel = c; tok = c.tokens ? c.tokens[0] : null;
  const tk = document.getElementById('toks'); tk.innerHTML = '';
  document.getElementById('details').classList.remove('hidden');
  for (const t of c.tokens || []) {
    const tb = document.createElement('button');
    tb.className = 'tok'; tb.textContent = t.label; tb.setAttribute('aria-pressed', String(t === tok));
    tb.onclick = () => { tok = t; for (const x of tk.children) x.setAttribute('aria-pressed', String(x === tb)); paint(); };
    tk.appendChild(tb);
  }
  paint();
}
function paint() {
  const parts = ['Отправляйте ТОЛЬКО ' + (tok ? tok.label + ' в сети ' : '') + sel.net];
  if (sel.warn) parts.push(sel.warn);
  if (tok && tok.contract) parts.push('контракт токена: ' + tok.contract);
  document.querySelector('.warn').textContent = '⚠ ' + parts.join(' — ') + ' — при переводе из другой сети средства будут потеряны.';
  document.getElementById('addr').textContent = PAY_TO;
  // CDN с QR-библиотекой может не загрузиться: адрес важнее картинки, падать нельзя.
  if (typeof qrcode !== 'function') return;
  const qr = qrcode(0, 'M'); qr.addData(PAY_TO); qr.make();
  document.getElementById('qr').innerHTML = qr.createImgTag(4, 8);
}
document.getElementById('copy').onclick = async () => {
  try { await navigator.clipboard.writeText(PAY_TO); document.getElementById('done').textContent = 'Адрес скопирован.'; }
  catch (e) { document.getElementById('done').textContent = PAY_TO; }
};
</scr` + `ipt>
</body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}

function notFound() {
  const html = `<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Страница не найдена</title>
<style>${BASE_CSS}</style></head><body>
<div class="card"><h1>Страница не найдена</h1>
<div class="muted">Ссылка на оплату не существует или адрес получателя в ней некорректный.</div>
<p><a href="/">Реквизиты pay.pxbt.app</a></p></div>
</body></html>`;
  return new Response(html, { status: 404, headers: { 'content-type': 'text/html; charset=utf-8' } });
}
