/**
 * GET / — публичная страница «реквизиты для перевода»: выбор сети, адрес, QR.
 * Адреса читаются напрямую из KV через lib/config (как /api/address) — без self-fetch.
 * Без подписи владельца в реестре страница честно говорит, что реквизитов нет.
 */
import { CONFIG_KEY, defaultConfig } from '../lib/config.js';

const QR_JS = 'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js';
const CHAINS = [
  { id: 'tron', label: 'USDT · Tron (TRC20)', net: 'Tron (TRC20)' },
  { id: 'evm', label: 'USDT · Ethereum (ERC20)', net: 'Ethereum (ERC20)' },
  { id: 'solana', label: 'USDT · Solana', net: 'Solana' },
];

export async function onRequestGet({ env }) {
  const cfg = JSON.parse((await env.KV.get(CONFIG_KEY)) || JSON.stringify(defaultConfig()));
  const chains = CHAINS
    .map((c) => ({ ...c, address: (cfg.addresses || {})[c.id] }))
    .filter((c) => c.address);
  const inline = (v) => JSON.stringify(v).replace(/</g, '\\u003c');
  const html = `<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Реквизиты pay.pxbt.app</title>
<script src="${QR_JS}"></scr` + `ipt>
<style>
 body{font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;padding:16px;background:#0f1115;color:#e6e6e6}
 .card{background:#171a21;border-radius:12px;padding:20px;margin-top:16px}
 h1{font-size:20px;margin:8px 0 2px} .muted{color:#8a92a3;font-size:13px}
 .opt{display:block;width:100%;margin:8px 0;padding:14px;border:1px solid #2a2f3a;border-radius:10px;background:#1c2029;color:#e6e6e6;font-size:16px;text-align:left;cursor:pointer}
 .opt[aria-pressed=true]{border-color:#4f8cff;background:#203050}
 .warn{color:#ffb84d;font-weight:600;margin:12px 0}
 .addr{font-family:monospace;word-break:break-all;background:#10131a;padding:10px;border-radius:8px}
 button.act{width:100%;margin-top:10px;padding:12px;border:0;border-radius:10px;background:#4f8cff;color:#fff;font-size:15px;font-weight:600;cursor:pointer}
 #qr img{margin:12px auto;display:block;filter:invert(1) hue-rotate(180deg)}
 .hidden{display:none}
</style></head><body>
<div class="card"><h1>Реквизиты для перевода</h1>
<div class="muted">Выберите сеть — покажу адрес и QR.</div></div>
<div class="card">
 <div id="opts"></div>
 <div id="details" class="hidden">
  <p class="warn"></p>
  <div class="addr" id="addr"></div>
  <div id="qr"></div>
  <button class="act" id="copy">Скопировать адрес</button>
  <div class="muted" id="done" style="margin-top:8px"></div>
 </div>
</div>
<script>
const CHAINS = ${inline(chains)};
const el = (h) => { const d = document.createElement('div'); d.innerHTML = h; return d; };
const box = document.getElementById('opts');
if (!CHAINS.length) box.appendChild(el('<p class="warn">Реквизиты ещё не настроены.</p>'));
let sel = null;
for (const c of CHAINS) {
  const b = document.createElement('button');
  b.className = 'opt'; b.textContent = c.label; b.setAttribute('aria-pressed', 'false');
  b.onclick = () => {
    sel = c;
    for (const x of box.children) x.setAttribute('aria-pressed', String(x === b));
    document.getElementById('details').classList.remove('hidden');
    document.querySelector('.warn').textContent = '⚠ Отправляйте ТОЛЬКО USDT в сети ' + c.net + ' — при переводе из другой сети средства будут потеряны.';
    document.getElementById('addr').textContent = c.address;
    document.getElementById('qr').innerHTML = '';
    const qr = qrcode(0, 'M'); qr.addData(c.address); qr.make();
    document.getElementById('qr').innerHTML = qr.createImgTag(4, 8);
  };
  box.appendChild(b);
}
document.getElementById('copy').onclick = async () => {
  try { await navigator.clipboard.writeText(sel.address); document.getElementById('done').textContent = 'Адрес скопирован.'; }
  catch (e) { document.getElementById('done').textContent = sel.address; }
};
</scr` + `ipt>
</body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}
