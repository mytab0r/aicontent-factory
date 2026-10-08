/**
 * GET /admin — админка: подключение кошельков (подпись), галочки пар.
 * Защита: CF Access на пути /admin (email владельца) — настраивается в CF Zero Trust,
 * здесь никакой парольной логики нет; доступ к /api/admin/* тоже закрывается CF Access.
 */
import { PAIRS } from '../lib/config.js';

// JSON внутрь <script>: экранируем '<', чтобы данные не закрыли тег
const inline = (v) => JSON.stringify(v).replace(/</g, '\\u003c');

export async function onRequestGet({ env } = {}) {
  const providers = (env && env.PROVIDERS) || [];
  const html = `<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>pay.pxbt.app — админка</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:16px;background:#0f1115;color:#e6e6e6}
 .card{background:#171a21;border-radius:12px;padding:20px;margin-top:16px}
 button{padding:10px 14px;border:1px solid #2a2f3a;border-radius:10px;background:#1c2029;color:#e6e6e6;cursor:pointer;margin:4px 6px 4px 0}
 button.primary{background:#4f8cff;border-color:#4f8cff;color:#fff;font-weight:600}
 input[type=checkbox]{transform:scale(1.3);margin-right:8px}
 .addr{font-family:monospace;word-break:break-all}
 #log{white-space:pre-wrap;color:#8a92a3;font-size:13px;margin-top:12px}
 label.pairline{display:block;margin:8px 0}
</style></head><body>
<h1>pay.pxbt.app</h1>
<div class="card">
 <h3>1. Подключить кошелёк (подпись = доказательство владения)</h3>
 <button onclick="claim('evm')">EVM (MetaMask/инжектед)</button>
 <button onclick="claim('tron')">Tron (TronLink)</button>
 <button onclick="claim('solana')">Solana (Phantom)</button>
 <div id="addresses" class="addr"></div>
</div>
<div class="card">
 <h3>2. Какие пары показывать клиенту</h3>
 <div id="pairs"></div>
 <button class="primary" onclick="savePairs()">Сохранить</button>
</div>
<div id="providers"></div>
<div id="log"></div>
<script>
const PAIRS = ${inline(PAIRS)};
const PROVIDERS = ${inline(providers)};
const CHAINS = { evm: 'evm', tron: 'tron', solana: 'solana' };
const log = (m) => document.getElementById('log').textContent += m + '\\n';

async function claim(chain) {
  try {
    const r = await fetch('/api/claim/nonce', { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify({ chain }) });
    const { nonce, message } = await r.json();
    let address, signature;
    if (chain === 'evm') {
      const accs = await ethereum.request({ method: 'eth_requestAccounts' });
      address = accs[0];
      signature = await ethereum.request({ method: 'personal_sign', params: [message, address] });
    } else if (chain === 'tron') {
      if (!window.tronWeb || !tronWeb.ready) throw new Error('TronLink не подключён');
      address = tronWeb.defaultAddress.base58;
      signature = await tronWeb.trx.signMessageV2(message);
    } else {
      if (!window.solana || !solana.isPhantom) throw new Error('Phantom не найден');
      const resp = await solana.connect();
      address = resp.publicKey.toString();
      const encoded = new TextEncoder().encode(message);
      const signed = await solana.signMessage(encoded, 'utf8');
      signature = btoa(String.fromCharCode(...signed.signature));
    }
    const v = await fetch('/api/claim/verify', { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify({ chain, address, signature, nonce }) });
    const j = await v.json();
    if (j.ok) { log('✔ ' + chain + ': адрес сохранён ' + j.address); loadConfig(); }
    else log('✘ ' + chain + ': ' + (j.error || 'отказ') + (j.detail ? ' — ' + j.detail : ''));
  } catch (e) { log('✘ ' + chain + ': ' + e.message); }
}

async function loadConfig() {
  const cfg = await (await fetch('/api/admin/config')).json();
  const a = document.getElementById('addresses');
  a.innerHTML = Object.entries(cfg.addresses).map(([k, v]) => k + ': ' + v).join('<br>') || '<i>адреса ещё не подключены</i>';
  const p = document.getElementById('pairs');
  p.innerHTML = Object.keys(PAIRS).map((id) =>
    '<label class="pairline"><input type="checkbox" id="pair_' + id + '"' + (cfg.pairs[id] ? ' checked' : '') + '>' + PAIRS[id].label + '</label>'
  ).join('');
}
async function savePairs() {
  const pairs = {};
  for (const id of Object.keys(PAIRS)) pairs[id] = document.getElementById('pair_' + id).checked;
  const r = await fetch('/api/admin/config', { method: 'PUT', headers: {'content-type':'application/json'}, body: JSON.stringify({ pairs }) });
  log(r.ok ? '✔ пары сохранены' : '✘ ошибка сохранения');
}
// Провайдеры с полями описаны данными (config/payment-providers.json): новый провайдер = новая запись, UI не трогаем.
function renderProviders(list) {
  const root = document.getElementById('providers');
  root.textContent = '';
  for (const p of list.filter((x) => x.fields)) {
    const card = document.createElement('div'); card.className = 'card';
    const h = document.createElement('h3'); h.textContent = p.title; card.appendChild(h);
    for (const f of p.fields) {
      const lab = document.createElement('label'); lab.className = 'pairline'; lab.textContent = f.label + ' ';
      let inp;
      if (f.type === 'select') {
        inp = document.createElement('select');
        for (const o of f.options) { const op = document.createElement('option'); op.value = op.textContent = o; inp.appendChild(op); }
        inp.value = p.values[f.key] || f.options[0];
      } else {
        inp = document.createElement('input');
        inp.type = f.type === 'secret' ? 'password' : 'text';
        if (f.type === 'secret') { inp.value = ''; inp.placeholder = p.values[f.key] ? p.values[f.key] + ' (сохранён; пусто = не менять)' : 'не задан'; }
        else inp.value = p.values[f.key] || '';
      }
      inp.id = 'pv_' + p.id + '_' + f.key; inp.autocomplete = 'off';
      lab.appendChild(inp); card.appendChild(lab);
    }
    const save = document.createElement('button'); save.className = 'primary'; save.textContent = 'Сохранить';
    save.onclick = async () => {
      const body = {};
      for (const f of p.fields) body[f.key] = document.getElementById('pv_' + p.id + '_' + f.key).value;
      const r = await fetch('/api/admin/providers/' + p.id, { method: 'PUT', headers: {'content-type':'application/json'}, body: JSON.stringify(body) });
      const j = await r.json();
      log(r.ok ? '✔ ' + p.title + ': сохранено' : '✘ ' + p.title + ': ' + (j.error || r.status));
      if (r.ok) loadProviders();
    };
    card.appendChild(save);
    if (p.check) {
      const chk = document.createElement('button'); chk.textContent = 'Проверить';
      chk.onclick = async () => {
        const j = await (await fetch('/api/admin/providers/' + p.id + '/check', { method: 'POST' })).json();
        log(j.ok ? '✔ ' + p.title + ': ключи рабочие' + (j.mode ? ' (' + j.mode + ')' : '') : '✘ ' + p.title + ': ' + j.error);
      };
      card.appendChild(chk);
    }
    root.appendChild(card);
  }
}
async function loadProviders() {
  const r = await fetch('/api/admin/providers');
  if (r.ok) renderProviders(await r.json());
}
renderProviders(PROVIDERS);
loadConfig();
</script>
</body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}
