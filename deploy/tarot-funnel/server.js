/**
 * tarot-funnel server — extends pay.pxbt.app with free tarot tier + ManyChat integration
 * Runs on same container, different port or path prefix
 * Env: PORT, DATA_DIR, MANYCHAT_PAGE_ID, MANYCHAT_TOKEN, PAY_API_TOKEN
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { timingSafeEqual } from 'node:crypto';

const here = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.DATA_DIR || '/data';
const PORT = Number(process.env.PORT || 8081);
const MANYCHAT_PAGE_ID = process.env.MANYCHAT_PAGE_ID || '';
const MANYCHAT_TOKEN = process.env.MANYCHAT_TOKEN || '';
const PAY_API_TOKEN = process.env.PAY_API_TOKEN || '';

// Simple file-based KV for tracking used wallets (prevent abuse)
class FileKV {
  constructor(file) { this.file = file; this.load(); }
  load() { this.m = fs.existsSync(this.file) ? JSON.parse(fs.readFileSync(this.file, 'utf8')) : {}; }
  save() { 
    const tmp = this.file + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(this.m), { mode: 0o600 });
    fs.chmodSync(tmp, 0o600);
    fs.renameSync(tmp, this.file); 
  }
  async get(k) { 
    const e = this.m[k];
    if (!e) return null;
    if (e.exp && e.exp < Date.now()) { delete this.m[k]; this.save(); return null; }
    return e.v; 
  }
  async put(k, v, opt = {}) { 
    this.m[k] = { v, ...(opt.expirationTtl ? { exp: Date.now() + opt.expirationTtl * 1000 } : {}) }; 
    this.save(); 
  }
}

const kv = new FileKV(path.join(DATA_DIR, 'tarot-kv.json'));
const usedWallets = new FileKV(path.join(DATA_DIR, 'tarot-used-wallets.json'));

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { 
  status, 
  headers: { 'content-type': 'application/json', 'cache-control': 'no-store', 'access-control-allow-origin': '*' } 
});

function safeEq(a, b) {
  const x = Buffer.from(String(a)), y = Buffer.from(String(b));
  return x.length === y.length && timingSafeEqual(x, y);
}

function validateWallet(addr) {
  const isTron = addr.startsWith('T') && addr.length === 34;
  const isEvm = addr.startsWith('0x') && addr.length === 42;
  const isSolana = addr.length >= 32 && addr.length <= 44 && /^[1-9A-HJ-NP-Za-km-z]+$/.test(addr);
  return { valid: isTron || isEvm || isSolana, chain: isTron ? 'tron' : isEvm ? 'evm' : isSolana ? 'solana' : null };
}

async function callPayApi(endpoint, body) {
  const res = await fetch('https://pay.pxbt.app' + endpoint, {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${PAY_API_TOKEN}`
    },
    body: JSON.stringify(body)
  });
  return { ok: res.ok, data: await res.json().catch(() => ({})) };
}

async function createFreeInvoice(wallet) {
  // Check if wallet already used free tier
  const used = await usedWallets.get(wallet);
  if (used) return { ok: false, error: 'Этот кошелек уже получил бесплатную раскладку' };
  
  // Call pay.pxbt.app to create invoice
  const result = await callPayApi('/api/invoice', { 
    wallet, 
    tier: 'free_tarot',
    amount: 0,
    metadata: { source: 'tarot-funnel' }
  });
  
  if (result.ok && result.data.id) {
    // Mark wallet as used (30 day expiry)
    await usedWallets.put(wallet, { usedAt: Date.now() }, { expirationTtl: 30 * 86400 });
    
    // Generate ManyChat ref URL
    const ref = `tarot_${Buffer.from(wallet).toString('base64url').slice(0, 16)}`;
    const manychatUrl = `https://m.me/${MANYCHAT_PAGE_ID}?ref=${ref}`;
    
    return { ok: true, manychat_url: manychatUrl, ref };
  }
  
  return { ok: false, error: result.data.error || 'Не удалось создать счёт' };
}

async function route(request) {
  const url = new URL(request.url);
  const p = url.pathname.replace(/\/+$/, '') || '/';
  const m = request.method;
  
  // CORS preflight
  if (m === 'OPTIONS') {
    return new Response(null, { 
      status: 204,
      headers: { 
        'access-control-allow-origin': '*',
        'access-control-allow-methods': 'GET,POST,OPTIONS',
        'access-control-allow-headers': 'Content-Type,Authorization'
      }
    });
  }
  
  // Serve static index.html
  if (p === '/' && m === 'GET') {
    const html = fs.readFileSync(path.join(here, 'index.html'), 'utf8');
    return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
  }
  
  // Health check
  if (p === '/healthz') return json({ ok: true, service: 'tarot-funnel' });
  
  // API: verify wallet and get ManyChat link
  if (p === '/api/tarot/verify' && m === 'POST') {
    try {
      const body = await request.json().catch(() => null);
      if (!body || !body.wallet) return json({ error: 'wallet required' }, 400);
      
      const { wallet } = body;
      const validation = validateWallet(wallet);
      if (!validation.valid) return json({ error: 'Неверный формат адреса' }, 400);
      
      const result = await createFreeInvoice(wallet);
      if (result.ok) {
        return json({ 
          ok: true, 
          manychat_url: result.manychat_url,
          message: 'Кошелек верифицирован. Переходите в ManyChat для раскладки.'
        });
      }
      return json({ error: result.error }, 400);
    } catch (e) {
      return json({ error: 'Internal error' }, 500);
    }
  }
  
  // API: get payment addresses for paid tiers
  if (p === '/api/tarot/addresses' && m === 'GET') {
    try {
      const res = await fetch('https://pay.pxbt.app/api/address');
      if (res.ok) {
        const data = await res.json();
        return json(data);
      }
    } catch (e) {}
    return json({ tron: '', evm: '', solana: '' });
  }
  
  // API: create paid subscription invoice
  if (p === '/api/tarot/subscribe' && m === 'POST') {
    // Require auth
    const bearer = (request.headers.get('authorization') || '').replace(/^Bearer /, '');
    if (!PAY_API_TOKEN || !safeEq(bearer, PAY_API_TOKEN)) {
      return json({ error: 'forbidden' }, 403);
    }
    
    try {
      const body = await request.json().catch(() => null);
      if (!body || !body.wallet || !body.tier) return json({ error: 'wallet and tier required' }, 400);
      
      const { wallet, tier } = body; // tier: 'basic' (15 USDT) or 'unlimited' (45 USDT)
      const amounts = { basic: 15, unlimited: 45 };
      const amount = amounts[tier];
      if (!amount) return json({ error: 'invalid tier' }, 400);
      
      const validation = validateWallet(wallet);
      if (!validation.valid) return json({ error: 'Неверный формат адреса' }, 400);
      
      const result = await callPayApi('/api/invoice', { 
        wallet, 
        tier: `tarot_${tier}`,
        amount,
        metadata: { source: 'tarot-funnel', tier }
      });
      
      return json(result.data, result.ok ? 200 : 400);
    } catch (e) {
      return json({ error: 'Internal error' }, 500);
    }
  }
  
  // ManyChat webhook callback (when user completes flow)
  if (p === '/api/tarot/manychat-callback' && m === 'POST') {
    // ManyChat can POST here with user data after flow completion
    try {
      const body = await request.json().catch(() => null);
      console.log('ManyChat callback:', JSON.stringify(body));
      // Could trigger delivery of tarot reading here
      return json({ ok: true });
    } catch (e) {
      return json({ error: 'Internal error' }, 500);
    }
  }
  
  return json({ error: 'not found' }, 404);
}

const srv = http.createServer(async (req, res) => {
  try {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const body = Buffer.concat(chunks);
    if (body.length > 64 * 1024) { res.writeHead(413).end(); return; }
    
    const request = new Request('http://' + (req.headers.host || 'localhost') + req.url, {
      method: req.method,
      headers: req.headers,
      body: ['GET', 'HEAD'].includes(req.method) ? undefined : body,
    });
    
    const r = await route(request);
    res.writeHead(r.status, Object.fromEntries(r.headers));
    res.end(Buffer.from(await r.arrayBuffer()));
  } catch (e) {
    console.error(e);
    if (!res.headersSent) res.writeHead(500, { 'content-type': 'application/json' });
    res.end('{"error":"internal"}');
  }
});

srv.listen(PORT, '0.0.0.0', () => console.log(`tarot-funnel listening on ${PORT}`));

// Graceful shutdown
process.on('SIGTERM', () => { srv.close(() => process.exit(0)); });
process.on('SIGINT', () => { srv.close(() => process.exit(0)); });
