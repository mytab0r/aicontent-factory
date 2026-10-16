/**
 * GET /admin — админка: подключение кошельков (подпись), галочки пар.
 * Защита: CF Access на пути /admin (email владельца) — настраивается в CF Zero Trust,
 * здесь никакой парольной логики нет; доступ к /api/admin/* тоже закрывается CF Access.
 */
import { PAIRS } from '../lib/config.js';
import { qrcodeFactory } from '../vendor/qrcode/qrcode.js';

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
 <button id="connect-evm" onclick="claim('evm')">EVM (MetaMask/инжектед)</button>
 <button id="connect-tron" onclick="claim('tron')">Tron (TronLink)</button>
 <button id="connect-solana" onclick="claim('solana')">Solana (Phantom)</button>
 <div id="addresses" class="addr"></div>
 <div id="nowallet" hidden>
  <p>Расширение кошелька в этом браузере не найдено. Откройте страницу в мобильном кошельке:
  отсканируйте QR телефоном или нажмите ссылку, затем подпишите там.</p>
  <p><a class="deeplink" target="_blank" rel="noopener"></a></p>
  <div class="qr" style="background:#fff;width:200px;padding:8px"></div>
 </div>
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

const qrcode = (${qrcodeFactory.toString()})();
const API_TIMEOUT = 15000;
const api = async (url, body) => {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), API_TIMEOUT);
  try {
    const r = await fetch(url, { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify(body), signal: ac.signal });
    return await r.json();
  } catch (e) { throw Object.assign(new Error('сеть недоступна'), { net: true }); }
  finally { clearTimeout(t); }
};
const hexUtf8 = (s) => '0x' + Array.from(new TextEncoder().encode(s), (b) => b.toString(16).padStart(2, '0')).join('');
const rejected = (e) => e && (e.code === 4001 || /declined|reject|denied|cancel/i.test(String(e.message || e)));

function eip6963() {
  return new Promise((res) => {
    let first = null;
    const on = (ev) => { if (!first && ev.detail && ev.detail.provider) first = ev.detail; };
    window.addEventListener('eip6963:announceProvider', on);
    window.dispatchEvent(new Event('eip6963:requestProvider'));
    setTimeout(() => { window.removeEventListener('eip6963:announceProvider', on); res(first); }, 300);
  });
}
const WALLETS = {
  evm: {
    async find() {
      const d = await eip6963();
      if (d) { log('evm: кошелёк ' + d.info.rdns); return d.provider; }
      return window.ethereum || null;
    },
    async connect(p) { return (await p.request({ method: 'eth_requestAccounts' }))[0]; },
    sign: (p, msg, address) => p.request({ method: 'personal_sign', params: [hexUtf8(msg), address] }),
  },
  tron: {
    async find() { return window.tron || window.tronLink || (window.tronWeb ? { tronWeb: window.tronWeb } : null); },
    async connect(p) {
      if (p.request) {
        const r = await p.request({ method: p === window.tron ? 'eth_requestAccounts' : 'tron_requestAccounts' });
        if (r && (r.code === 4001 || r.code === 4000)) throw { code: 4001 };
      }
      const tw = p.tronWeb || window.tronWeb;
      if (!tw || !tw.defaultAddress || !tw.defaultAddress.base58) throw new Error('TronLink заблокирован: разблокируйте кошелёк');
      return tw.defaultAddress.base58;
    },
    sign: (p, msg) => (p.tronWeb || window.tronWeb).trx.signMessageV2(msg),
  },
  solana: {
    async find() { return (window.phantom && window.phantom.solana) || window.solana || null; },
    async connect(p) { return (await p.connect()).publicKey.toString(); },
    async sign(p, msg) {
      const signed = await p.signMessage(new TextEncoder().encode(msg), 'utf8');
      return btoa(String.fromCharCode(...(signed.signature || signed)));
    },
  },
};
function deeplink(chain) {
  const u = location.href.split('#')[0];
  if (chain === 'evm') return 'https://link.metamask.io/dapp/' + location.host + location.pathname;
  if (chain === 'tron') return 'tronlinkoutside://pull.activity?param=' + encodeURIComponent(JSON.stringify({ url: u, action: 'open', protocol: 'tronlink', version: '1.0' }));
  return 'https://phantom.com/ul/browse/' + encodeURIComponent(u) + '?ref=' + encodeURIComponent(location.origin);
}
function showNoWallet(chain) {
  const box = document.getElementById('nowallet');
  const href = deeplink(chain);
  const a = box.querySelector('a.deeplink');
  a.href = href; a.textContent = 'Открыть в кошельке (' + chain + ')';
  const q = qrcode(0, 'M'); q.addData(href); q.make();
  box.querySelector('.qr').innerHTML = q.createSvgTag({ scalable: true, margin: 2 });
  box.hidden = false;
}

async function claim(chain) {
  const btn = document.getElementById('connect-' + chain);
  btn.disabled = true;
  let step = 'connect';
  try {
    const w = WALLETS[chain];
    const p = await w.find();
    if (!p) { log('✘ ' + chain + ': кошелёк не найден'); showNoWallet(chain); return; }
    document.getElementById('nowallet').hidden = true;
    const address = await w.connect(p);
    if (!address) throw new Error('кошелёк не вернул адрес');
    step = 'nonce';
    const { nonce, message } = await api('/api/claim/nonce', { chain });
    if (!nonce) throw new Error('сервер не выдал nonce');
    step = 'sign';
    const signature = await w.sign(p, message, address);
    step = 'verify';
    const j = await api('/api/claim/verify', { chain, address, signature, nonce });
    if (j.ok) { log('✔ ' + chain + ': адрес сохранён ' + j.address); await loadConfig(); }
    else log('✘ ' + chain + ': ' + (j.error || 'отказ') + (j.detail ? ' — ' + j.detail : ''));
  } catch (e) {
    if (e && e.net) log('✘ ' + chain + ': сеть недоступна');
    else if (rejected(e)) log('✘ ' + chain + ': ' + (step === 'connect' ? 'подключение отклонено в кошельке' : 'подпись отклонена в кошельке'));
    else log('✘ ' + chain + ': ' + ((e && e.message) || String(e)));
  } finally { btn.disabled = false; }
}

async function loadConfig() {
  const cfg = await (await fetch('/api/admin/config')).json();
  const a = document.getElementById('addresses');
  a.textContent = '';
  for (const [k, v] of Object.entries(cfg.addresses)) { const d = document.createElement('div'); d.textContent = k + ': ' + v; a.appendChild(d); }
  if (!a.firstChild) a.innerHTML = '<i>адреса ещё не подключены</i>';
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
