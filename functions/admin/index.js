/**
 * GET /admin — админка: подключение кошельков (подпись), галочки пар.
 * Защита: CF Access на пути /admin (email владельца) — настраивается в CF Zero Trust,
 * здесь никакой парольной логики нет; доступ к /api/admin/* тоже закрывается CF Access.
 */
import { PAIRS } from '../lib/config.js';

export async function onRequestGet() {
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
<div id="log"></div>
<script>
const PAIRS = ${JSON.stringify(PAIRS)};
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
loadConfig();
</script>
</body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}
