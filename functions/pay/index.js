/**
 * GET / — публичная страница «реквизиты для перевода»: выбор сети (и токена для EVM), адрес, QR.
 * Адреса читаются напрямую из KV через lib/config (как /api/address) — без self-fetch.
 * EVM-сети = один адрес (cfg.addresses.evm), выбор токена USDT/USDC; BTC/TON — отдельные адреса (вписывает владелец в админке).
 * Порядок по объёму USDT (DefiLlama 25.10.2026): Tron, Ethereum, BSC, Polygon, Arbitrum, Base, Solana, затем BTC, TON.
 * Без адреса пункт скрыт. LTC/XRP/DOGE не добавляем (риск отправки не в ту сеть).
 */
import { CONFIG_KEY, defaultConfig } from '../lib/config.js';

const QR_JS = 'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js';
export const EVM_TOKENS = [
  { id: 'usdt', label: 'USDT', contracts: { eth: '0xdAC17F958D2ee523a2206206994597C13D831ec7', bsc: '0x55d398326f99059fF775485246999027B3197955', poly: '0xc2132D05D31c914a87C6611C10748AEb04B58e8F', arb: '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9', base: null } },
  { id: 'usdc', label: 'USDC', contracts: { eth: '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', bsc: '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', poly: '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359', arb: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831', base: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913' } },
];
export const NETWORKS = [
  { id: 'tron', label: 'USDT · Tron (TRC20)', net: 'Tron (TRC20)', warn: null },
  { id: 'evm:eth', label: 'Ethereum (ERC20)', net: 'Ethereum (ERC20)', warn: 'высокая комиссия сети', evm: true },
  { id: 'evm:bsc', label: 'BNB Smart Chain (BEP20)', net: 'BSC (BEP20)', warn: null, evm: true },
  { id: 'evm:poly', label: 'Polygon (PoS)', net: 'Polygon (PoS)', warn: null, evm: true },
  { id: 'evm:arb', label: 'Arbitrum One', net: 'Arbitrum One', warn: null, evm: true },
  { id: 'evm:base', label: 'Base', net: 'Base', warn: null, evm: true },
  { id: 'solana', label: 'USDT · Solana', net: 'Solana', warn: null },
  { id: 'btc', label: 'Bitcoin (BTC)', net: 'Bitcoin', warn: 'подтверждения 10–30 мин' },
  { id: 'ton', label: 'TON', net: 'TON', warn: null },
];

export async function onRequestGet({ env = {} }) {
  const projectId = env.REOWN_PROJECT_ID || '';
  const cfg = JSON.parse((await env.KV.get(CONFIG_KEY)) || JSON.stringify(defaultConfig()));
  const a = cfg.addresses || {};
  const nets = NETWORKS
    .map((n) => {
      const [kind, sub] = n.id.split(':');
      if (kind === 'evm') return { ...n, address: a.evm, tokens: EVM_TOKENS.map((t) => ({ id: t.id, label: t.label, contract: t.contracts[sub] })).filter((t) => t.contract) };
      return { ...n, address: a[kind] };
    })
    .filter((n) => n.address);
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
 .opt small{color:#8a92a3;margin-left:8px}
 .tok{display:inline-block;width:auto;margin:6px 6px 0 0;padding:8px 14px;border:1px solid #2a2f3a;border-radius:8px;background:#1c2029;color:#e6e6e6;font-size:14px;cursor:pointer}
 .tok[aria-pressed=true]{border-color:#4f8cff;background:#203050}
 .warn{color:#ffb84d;font-weight:600;margin:12px 0;overflow-wrap:anywhere}
 .addr{font-family:monospace;word-break:break-all;background:#10131a;padding:10px;border-radius:8px}
 button.act{width:100%;margin-top:10px;padding:12px;border:0;border-radius:10px;background:#4f8cff;color:#fff;font-size:15px;font-weight:600;cursor:pointer}
 #qr img{margin:12px auto;display:block;filter:invert(1) hue-rotate(180deg)}
 .hidden{display:none}
</style></head><body>
<div class="card"><h1>Реквизиты для перевода</h1>
<div class="muted">Выберите сеть — покажу адрес и QR.</div>
<div id="wc-box">
 <button class="act" id="wc">Подключить кошелёк</button>
 <div class="muted" id="wcstate" style="margin-top:8px"></div>
</div></div>
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
const el = (h) => { const d = document.createElement('div'); d.innerHTML = h; return d; };
const box = document.getElementById('opts');
if (!NETS.length) box.appendChild(el('<p class="warn">Реквизиты ещё не настроены.</p>'));

// Рендерим все сети сразу карточками
for (const c of NETS) {
  const card = document.createElement('div');
  card.className = 'card';
  card.style.marginTop = '16px';

  // Заголовок сети
  const h = document.createElement('h3');
  h.style.margin = '0 0 8px';
  h.textContent = c.label;
  card.appendChild(h);

  // Токены для EVM-сетей
  if (c.tokens && c.tokens.length) {
    const tk = document.createElement('div');
    tk.style.marginBottom = '8px';
    for (const t of c.tokens) {
      const tb = document.createElement('button');
      tb.className = 'tok';
      tb.textContent = t.label;
      tb.style.margin = '4px 6px 4px 0';
      tb.dataset.contract = t.contract || '';
      tb.onclick = () => {
        for (const x of tk.children) x.setAttribute('aria-pressed', 'false');
        tb.setAttribute('aria-pressed', 'true');
        paintCard(card, c, t);
      };
      tk.appendChild(tb);
    }
    card.appendChild(tk);
    // Дефолт — первый токен
    paintCard(card, c, c.tokens[0]);
  } else {
    paintCard(card, c, null);
  }

  box.appendChild(card);
}

function paintCard(card, c, t) {
  // Удаляем старые addr/qr/copy/done если есть
  const old = card.querySelector('.addr-row');
  if (old) old.remove();

  const row = document.createElement('div');
  row.className = 'addr-row';
  row.style.display = 'flex';
  row.style.flexDirection = 'column';
  row.style.gap = '8px';

  const parts = ['Отправляйте ТОЛЬКО ' + (t ? t.label + ' в сети ' : '') + c.net];
  if (c.warn) parts.push(c.warn);
  if (t) parts.push('контракт токена: ' + t.contract);
  const warn = document.createElement('p');
  warn.className = 'warn';
  warn.textContent = '⚠ ' + parts.join(' — ') + ' — при переводе из другой сети средства будут потеряны.';
  row.appendChild(warn);

  const addr = document.createElement('div');
  addr.className = 'addr';
  addr.textContent = c.address;
  row.appendChild(addr);

  const qr = document.createElement('div');
  qr.id = 'qr-' + c.id;
  row.appendChild(qr);

  const copyBtn = document.createElement('button');
  copyBtn.className = 'act';
  copyBtn.textContent = 'Скопировать адрес';
  copyBtn.onclick = async () => {
    try { await navigator.clipboard.writeText(c.address); copyBtn.textContent = 'Скопировано!'; setTimeout(() => copyBtn.textContent = 'Скопировать адрес', 2000); }
    catch (e) { copyBtn.textContent = c.address; }
  };
  row.appendChild(copyBtn);

  card.appendChild(row);

  // QR
  if (typeof qrcode === 'function') {
    const qrgen = qrcode(0, 'M');
    qrgen.addData(c.address);
    qrgen.make();
    qr.innerHTML = qrgen.createImgTag(4, 8);
  }
}

const PROJECT_ID = ${inline(projectId)};
const APPKIT_NETS = [{ id: 1, name: 'Ethereum', nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 }, rpcUrls: { default: { http: ['https://eth.llamarpc.com'] } } }, { id: 8453, name: 'Base', nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 }, rpcUrls: { default: { http: ['https://mainnet.base.org'] } } }];
const wcBtn = document.getElementById('wc');
const wcState = document.getElementById('wcstate');
if (!PROJECT_ID && !window.__appkit) { wcBtn.hidden = true; wcState.textContent = 'WalletConnect не настроен (нет projectId).'; }
let appkitP = null;
async function appkit() {
  if (window.__appkit) return window.__appkit.modal;
  if (!PROJECT_ID) throw new Error('WalletConnect не настроен');
  appkitP = appkitP || Promise.all([
    import('https://esm.sh/@reown/appkit@1.7.18'),
    import('https://esm.sh/@reown/appkit-adapter-wagmi@1.7.18'),
  ]).then(([{ createAppKit }, { WagmiAdapter }]) => {
    const wagmiAdapter = new WagmiAdapter({ networks: APPKIT_NETS, projectId: PROJECT_ID });
    const modal = createAppKit({ adapters: [wagmiAdapter], networks: APPKIT_NETS, projectId: PROJECT_ID, features: { analytics: false, email: false, socials: false, swaps: false, onramp: false } });
    window.__appkit = { modal, wagmiConfig: wagmiAdapter.wagmiConfig };
    return modal;
  });
  return appkitP;
}
wcBtn.onclick = async () => {
  wcBtn.disabled = true;
  wcState.textContent = 'Открываю список кошельков…';
  try {
    const modal = await appkit();
    // Висячая WC-сессия без аккаунта дизейблит кошельки в модалке (hasAnyConnection). Сбрасываем.
    try { await modal.disconnect(); } catch (e) {}
    await modal.open();
    wcState.textContent = '';
  } catch (e) {
    wcState.textContent = 'Кошелёк не открылся: ' + ((e && e.message) || e) + '. Откройте эту страницу в браузере кошелька (SafePal → Discover).';
  } finally { wcBtn.disabled = false };
};
</scr` + `ipt>
</body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}
