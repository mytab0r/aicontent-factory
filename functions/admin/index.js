/**
 * GET /admin — админка: подключение кошельков (подпись), галочки пар.
 * Защита: CF Access на пути /admin (email владельца) — настраивается в CF Zero Trust,
 * здесь никакой парольной логики нет; доступ к /api/admin/* тоже закрывается CF Access.
 *
 * Кошельки — Reown AppKit (WalletConnect), одна кнопка <appkit-button>:
 * мобила = список установленных кошельков (SafePal, Trust, MetaMask, OKX...), деск = расширения/QR.
 * EVM-подпись personal_sign через универсальный EIP-1193 провайдер AppKit;
 * Solana — window-провайдер (Phantom/SafePal); Tron — прямой TIP-1193 (AppKit Tron-адаптера нет).
 * TON — TON Connect (@tonconnect/ui, manifest на pay.pxbt.app/tonconnect-manifest.json), ton_proof
 *       верифицируется сервером криптографически (StateInit -> публичный ключ, без доверия клиенту).
 * BTC — injected-провайдеры (window.phantom.bitcoin, window.unisat, window.okxwallet.bitcoin, window.xverse);
 *       только bc1q (P2WPKH) адрес, signMessage как доказательство владения.
 * projectId приходит из env.REOWN_PROJECT_ID (прод: secrets.json; e2e: инжект).
 */
import { PAIRS } from '../lib/config.js';

const inline = (v) => JSON.stringify(v).replace(/</g, '\\u003c');

export async function onRequestGet({ env } = {}) {
  const providers = (env && env.PROVIDERS) || [];
  const projectId = (env && env.REOWN_PROJECT_ID) || '';
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
 appkit-button{margin:4px 0}
</style>
<script type="module">
 try {
  const [{ createAppKit }, { WagmiAdapter }] = await Promise.all([
    import('https://esm.sh/@reown/appkit@1.7.18'),
    import('https://esm.sh/@reown/appkit-adapter-wagmi@1.7.18'),
  ]);
  const projectId = ${inline(projectId)};
  const networks = [{ id: 1, name: 'Ethereum', nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 }, rpcUrls: { default: { http: ['https://eth.llamarpc.com'] } } }, { id: 8453, name: 'Base', nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 }, rpcUrls: { default: { http: ['https://mainnet.base.org'] } } }];
  const wagmiAdapter = new WagmiAdapter({ networks, projectId });
  // email/socials выкл.: иначе AppKit сверяет allowlist клиентом и бракует запись без схемы ('pay.pxbt.app') -> 'Invalid App Configuration'.
  const modal = createAppKit({ adapters: [wagmiAdapter], networks, projectId, features: { analytics: false, email: false, socials: false, swaps: false, onramp: false } });
  window.__appkit = { modal, wagmiConfig: wagmiAdapter.wagmiConfig };
 } catch (e) { window.__appkitError = String(e && e.message || e); }
</script></head><body>
<h1>pay.pxbt.app</h1>
<div class="card">
 <h3>1. Подключить кошелёк (подпись = доказательство владения)</h3>
 <button id="connect-all" class="primary" onclick="claimAll()">Подключить кошелек</button>
 <div id="addresses" class="addr"></div>
 <div id="nowallet" hidden><p id="nowallet-msg"></p></div>
 <div id="ton-connect-button" hidden></div>
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
const log = (m) => document.getElementById('log').textContent += m + '\\n';
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
const rejected = (e) => e && (e.code === 4001 || /declined|reject|denied|cancel/i.test(String((e && e.message) || e)));
const nonceMsg = (nonce) => 'pay.pxbt.app: claim ' + nonce + '\\nвладелец pxbt.app';

const wagmiCore = () => import('https://esm.sh/@wagmi/core@2');

// EVM: сначала инжектед-кошелёк (EIP-6963 / window.ethereum) — десктоп-расширения и dApp-браузеры кошельков;
// иначе AppKit (WalletConnect): модалка со списком кошельков и QR.
function injectedEvm() {
  return new Promise((res) => {
    let first = null;
    const on = (ev) => { if (!first && ev.detail && ev.detail.provider) first = ev.detail; };
    window.addEventListener('eip6963:announceProvider', on);
    window.dispatchEvent(new Event('eip6963:requestProvider'));
    setTimeout(() => { window.removeEventListener('eip6963:announceProvider', on); res(first || (window.ethereum ? { provider: window.ethereum } : null)); }, 300);
  });
}
// Telegram WebView / iOS без инжектед-кошелька: WalletConnect deep links там ненадёжны -> подсказка SafePal сразу.
const isTelegramWebView = () => /Telegram/i.test(navigator.userAgent);
const isIOS = () => /iPhone|iPad|iPod/i.test(navigator.userAgent);
const needsWalletBrowser = () => isTelegramWebView() || (isIOS() && !window.ethereum);
const NOWALLET_HINT = 'Откройте pay.pxbt.app/admin в SafePal → Discover (вставьте адрес в строку поиска) и нажмите «Подключить кошелек». Или в Safari: в Telegram «…» → Открыть в Safari.';
function showNoWalletHint() {
  document.getElementById('nowallet-msg').textContent = NOWALLET_HINT;
  document.getElementById('nowallet').hidden = false;
}
// AppKit (WalletConnect): уже подключённая сессия или модалка + ожидание подключения (до 3 мин).
async function appkitEvm() {
  const m = window.__appkit.modal;
  const addr = () => { try { const a = m.getAccount('eip155'); return a && a.isConnected && a.address; } catch (e) { return null; } };
  if (!addr()) {
    // Висящая WC-сессия без аккаунта (прошлая попытка/другая сеть) дизейблит все кошельки в модалке (AppKit: hasAnyConnection). Сбрасываем.
    try { await m.disconnect(); } catch (e) {}
    // iOS Telegram in-app browser: deep links из модалки не работают — сразу подсказка, модалка вторична.
    if (isTelegramWebView()) {
      throw Object.assign(new Error('кошелёк не найден'), { nowallet: true });
    }
    await m.open();
    // Модалку закрыли — выходим сразу ({code:4001,connect:true}), иначе кнопка висит disabled до 180 с.
    for (let t = 0; !addr(); t += 500) {
      if (!m.getState().open) throw Object.assign(new Error('подключение отклонено'), { code: 4001, connect: true });
      if (t > 180000) throw Object.assign(new Error('подключение отклонено'), { code: 4001, connect: true });
      await new Promise((r) => setTimeout(r, 500));
    }
    try { await m.close(); } catch (e) {}
  }
  const p = m.getWalletProvider();
  if (!p) throw new Error('WalletConnect: провайдер не получен');
  return { provider: p, address: addr() };
}
async function evmWallet() {
  const inj = await injectedEvm();
  if (!inj && (window.__appkitError || !window.__appkit)) throw Object.assign(new Error('кошелёк не найден'), { nowallet: true });
  const wc = inj ? null : await appkitEvm();
  const p = inj ? inj.provider : wc.provider;
  let accs = wc ? [wc.address] : null;
  if (!wc) {
    try { accs = await p.request({ method: 'eth_requestAccounts' }); }
    catch (e) { throw Object.assign(new Error('подключение отклонено'), { code: 4001, connect: true }); }
  }
  const address = accs && accs[0];
  if (!address) throw new Error('кошелёк не вернул адрес');
  return {
    address,
    async sign(msg) {
      try { return await p.request({ method: 'personal_sign', params: [hexUtf8(msg), address] }); }
      catch (e) { throw Object.assign(new Error('подпись отклонена'), { code: (e && e.code) || 4001 }); }
    },
  };
}

// Solana: window-провайдер (SafePal/Phantom в dApp-браузере, расширение на десктопе)
async function solanaWallet() {
  const p = (window.phantom && window.phantom.solana) || window.solana;
  if (!p) throw Object.assign(new Error('кошелёк не найден'), { nowallet: true });
  let res;
  try { res = await p.connect(); }
  catch (e) { throw Object.assign(new Error('подключение отклонено'), { code: (e && e.code) || 4001, connect: true }); }
  const pk = (res && res.publicKey) || p.publicKey;
  if (!pk) throw new Error('кошелёк не вернул адрес');
  return {
    address: pk.toString(),
    async sign(msg) {
      const s = await p.signMessage(new TextEncoder().encode(msg), 'utf8');
      return btoa(String.fromCharCode(...(s.signature || s)));
    },
  };
}

// Tron: TIP-1193 напрямую (TronLink/SafePal dApp-браузер)
async function tronWallet() {
  const p = window.tron || window.tronLink || (window.tronWeb ? { tronWeb: window.tronWeb } : null);
  if (!p) throw Object.assign(new Error('кошелёк не найден'), { nowallet: true });
  if (p.request) {
    let r;
    try { r = await p.request({ method: p === window.tron ? 'eth_requestAccounts' : 'tron_requestAccounts' }); }
    catch (e) { throw Object.assign(new Error('подключение отклонено'), { code: (e && e.code) || 4001, connect: true }); }
    if (r && (r.code === 4001 || r.code === 4000)) throw Object.assign(new Error('подключение отклонено'), { code: 4001, connect: true });
  }
  const tw = p.tronWeb || window.tronWeb;
  if (!tw || !tw.defaultAddress || !tw.defaultAddress.base58) throw new Error('TronLink заблокирован: разблокируйте кошелёк');
  return { address: tw.defaultAddress.base58, async sign(msg) { return tw.trx.signMessageV2(msg); } };
}

const WALLETS = { evm: evmWallet, solana: solanaWallet, tron: tronWallet, ton: tonWallet, btc: btcWallet };

// TON: TON Connect (@tonconnect/ui) + ton_proof. Сервер верифицирует proof криптографически
// (StateInit -> публичный ключ), payload proof'а = выданный сервером nonce (anti-replay).
let tonConnectUiPromise = null;
function getTonConnectUi() {
  if (!tonConnectUiPromise) {
    // window.__TonConnectUIClass: e2e/test hook — avoids a real esm.sh network import.
    tonConnectUiPromise = (window.__TonConnectUIClass
      ? Promise.resolve({ TonConnectUI: window.__TonConnectUIClass })
      : import('https://esm.sh/@tonconnect/ui@2.2.2')
    ).then(({ TonConnectUI }) =>
      new TonConnectUI({ manifestUrl: 'https://pay.pxbt.app/tonconnect-manifest.json', buttonRootId: 'ton-connect-button' })
    );
  }
  return tonConnectUiPromise;
}
async function tonWallet(message) {
  const ui = await getTonConnectUi();
  ui.setConnectRequestParameters({ state: 'ready', value: { tonProof: message } });
  if (ui.connected) await ui.disconnect().catch(() => {});
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      unsub();
      reject(Object.assign(new Error('подключение отклонено'), { code: 4001, connect: true }));
    }, 180000);
    const unsub = ui.onStatusChange((wallet) => {
      if (!wallet) return;
      clearTimeout(timeout);
      unsub();
      const proofItem = wallet.connectItems && wallet.connectItems.tonProof;
      if (!proofItem || !('proof' in proofItem)) {
        reject(new Error('кошелёк не вернул ton_proof'));
        return;
      }
      resolve({
        address: wallet.account.address,
        async sign() {
          return JSON.stringify({
            address: wallet.account.address,
            stateInit: wallet.account.walletStateInit,
            proof: proofItem.proof,
          });
        },
      });
    });
    ui.connect().catch((e) => { clearTimeout(timeout); unsub(); reject(e); });
  });
}

// BTC: injected-провайдеры (Phantom/Unisat/OKX/Xverse). Только bc1q (P2WPKH) — taproot/legacy отклоняются
// сразу на клиенте; сервер всё равно перепроверяет (derived-address должен совпасть с подписью).
async function btcWallet() {
  const provider = (window.phantom && window.phantom.bitcoin) || window.unisat || (window.okxwallet && window.okxwallet.bitcoin) || window.xverse;
  if (!provider) throw Object.assign(new Error('кошелёк не найден'), { nowallet: true });
  let accounts;
  try {
    accounts = (await (provider.requestAccounts ? provider.requestAccounts() : provider.request({ method: 'requestAccounts' }))) || [];
  } catch (e) {
    throw Object.assign(new Error('подключение отклонено'), { code: (e && e.code) || 4001, connect: true });
  }
  const toAddr = (a) => (typeof a === 'string' ? a : a && a.address);
  const bech32 = accounts.map(toAddr).find((a) => a && a.startsWith('bc1q'));
  if (!bech32) throw new Error('только bc1q (P2WPKH) адреса принимаются');
  return {
    address: bech32,
    async sign(msg) {
      try {
        if (provider.signMessage) return await provider.signMessage(msg, bech32);
        return await provider.request({ method: 'signMessage', params: [msg, bech32] });
      } catch (e) { throw Object.assign(new Error('подпись отклонена'), { code: (e && e.code) || 4001 }); }
    },
  };
}

async function claim(chain) {
  const btn = document.getElementById('connect-all');
  btn.disabled = true;
  try {
    let w, nonce, message;
    if (chain === 'ton') {
      // TON Connect подписывает nonce как ton_proof payload в процессе подключения —
      // nonce нужен ДО вызова кошелька (в отличие от остальных цепочек).
      ({ nonce, message } = await api('/api/claim/nonce', { chain }));
      if (!nonce) throw new Error('сервер не выдал nonce');
      w = await WALLETS[chain](message || nonceMsg(nonce));
    } else {
      w = await WALLETS[chain]();
      ({ nonce, message } = await api('/api/claim/nonce', { chain }));
      if (!nonce) throw new Error('сервер не выдал nonce');
    }
    const address = w.address;
    if (!address) throw new Error('кошелёк не вернул адрес');
    const signature = await w.sign(message || nonceMsg(nonce));
    const j = await api('/api/claim/verify', { chain, address, signature, nonce });
    if (j.ok) { log('✔ ' + chain + ': адрес сохранён ' + j.address); await loadConfig(); }
    else log('✘ ' + chain + ': ' + (j.error || 'отказ') + (j.detail ? ' — ' + j.detail : ''));
  } catch (e) {
    if (e && e.net) log('✘ ' + chain + ': сеть недоступна');
    else if (rejected(e)) log('✘ ' + chain + ': ' + (e && e.connect ? 'подключение отклонено в кошельке' : 'подпись отклонена в кошельке'));
    else if (e && e.nowallet) {
      log('✘ ' + chain + ': кошелёк не найден');
      showNoWalletHint();
    }
    else log('✘ ' + chain + ': ' + ((e && e.message) || String(e)));
  } finally { btn.disabled = false; }
}
window.claim = claim;
window.claimChain = claim;

// Одна кнопка: подключает ВСЕ цепочки кошелька по очереди (SafePal/Trust = evm+tron+solana сразу).
// Ни одного провайдера -> открываем AppKit-модалку (WalletConnect: список кошельков/QR).
async function claimAll() {
  const btn = document.getElementById('connect-all');
  btn.disabled = true;
  const CHAINS = ['evm', 'tron', 'solana', 'btc', 'ton'];
  let errors = 0;
  try {
    for (const chain of CHAINS) {
      try { await claim(chain); }
      catch (e) { errors++; }
    }
    if (errors) log('⚠ не все цепочки подключены (' + errors + ' ошибок) — смотри выше');
  } finally { btn.disabled = false; }
}
window.claimAll = claimAll;

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
window.savePairs = savePairs;
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
        for (const o of f.options) { const op = document.createElement('option'); op.value = o; op.textContent = o; if (p.values[f.key] === o) op.selected = true; inp.appendChild(op); }
      } else {
        inp = document.createElement('input');
        inp.type = f.type === 'secret' ? 'password' : 'text';
        inp.value = p.values[f.key] || '';
        inp.autocomplete = 'off';
      }
      inp.dataset.field = f.key; inp.dataset.provider = p.id;
      lab.appendChild(inp); card.appendChild(lab);
    }
    const b = document.createElement('button');
    b.textContent = 'Сохранить и проверить';
    b.onclick = async () => {
      const body = {};
      for (const i of card.querySelectorAll('[data-field]')) body[i.dataset.field] = i.value;
      const r = await fetch('/api/admin/providers/' + p.id, { method: 'PUT', headers: {'content-type':'application/json'}, body: JSON.stringify(body) });
      if (!r.ok) { log('✘ ' + p.title + ': ' + (await r.json()).error); return; }
      const c = await fetch('/api/admin/providers/' + p.id + '/check', { method: 'POST' });
      const j = await c.json();
      log(j.ok ? '✔ ' + p.title + ': ok (' + (j.mode || '') + ')' : '✘ ' + p.title + ': ' + j.error);
      loadProviders();
    };
    card.appendChild(b);
    root.appendChild(card);
  }
}
async function loadProviders() {
  const list = await (await fetch('/api/admin/providers')).json();
  renderProviders(list);
}
loadConfig().catch((e) => log('✘ конфиг: ' + e.message));
// Инжект провайдера кошелька может прийти чуть позже загрузки — проверяем через 500 мс.
setTimeout(() => { if (needsWalletBrowser()) showNoWalletHint(); }, 500);
loadProviders().catch(() => {});
</script></body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
}
