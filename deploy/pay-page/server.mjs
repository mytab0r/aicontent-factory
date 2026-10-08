/**
 * pay.pxbt.app в контейнере (ghcr -> Watchtower на VPS). Node stdlib, без npm-зависимостей.
 * Переиспользует обработчики functions/ (те же, что в Pages Functions) через адаптер:
 *   KV        -> JSON-файл $DATA_DIR/kv.json (атомарная запись, TTL)
 *   секреты   -> $DATA_DIR/secrets.json, chmod 600, вне git; наружу только маска
 * Админка (/admin, /api/admin/*, /api/claim/*): только владелец через Cloudflare Access —
 * JWT из Cf-Access-Jwt-Assertion проверяется по ключам команды (RS256, aud, iss, exp, email).
 * Без CF_ACCESS_TEAM_DOMAIN/CF_ACCESS_AUD админка закрыта (fail closed).
 * Env: PORT, DATA_DIR, OWNER_EMAIL, CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD, PAY_API_TOKEN.
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { timingSafeEqual } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import * as adminPage from '../../functions/admin/index.js';
import * as adminConfig from '../../functions/api/admin/config.js';
import * as claimNonce from '../../functions/api/claim/nonce.js';
import * as claimVerify from '../../functions/api/claim/verify.js';
import * as invoiceCreate from '../../functions/api/invoice/create.js';
import * as invoiceApi from '../../functions/api/invoice/[[id]].js';
import * as invoicePage from '../../functions/i/[[id]].js';

const here = path.dirname(fileURLToPath(import.meta.url));
const PROVIDERS_FILE = [path.join(here, 'payment-providers.json'), path.join(here, '../../config/payment-providers.json')].find((f) => fs.existsSync(f));
const MASK = '••••••••';

function writeAtomic(file, data, mode) {
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, data, { mode });
  fs.chmodSync(tmp, mode);
  fs.renameSync(tmp, file);
}

class FileKV {
  constructor(file) { this.file = file; this.load(); }
  load() { this.m = fs.existsSync(this.file) ? JSON.parse(fs.readFileSync(this.file, 'utf8')) : {}; }
  save() { writeAtomic(this.file, JSON.stringify(this.m), 0o600); }
  async get(k) {
    const e = this.m[k];
    if (!e) return null;
    if (e.exp && e.exp < Date.now()) { delete this.m[k]; this.save(); return null; }
    return e.v;
  }
  async put(k, v, opt = {}) { this.m[k] = { v, ...(opt.expirationTtl ? { exp: Date.now() + opt.expirationTtl * 1000 } : {}) }; this.save(); }
  async delete(k) { delete this.m[k]; this.save(); }
}

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
const b64u = (s) => Buffer.from(s, 'base64url');

let certCache = { at: 0, keys: [] };
/** Cloudflare Access JWT -> email владельца или null. */
async function accessEmail(request, { team, aud, owner }) {
  // CF_ACCESS_AUD может быть списком через запятую: JWT несёт aud того приложения
  // Access, которым закрыт конкретный путь (/admin, /api/admin, /api/claim).
  const audsEnv = String(aud || '').split(',').map((s) => s.trim()).filter(Boolean);
  if (!team || !audsEnv.length || !owner) return null;
  const cookie = (request.headers.get('cookie') || '').match(/CF_Authorization=([^;]+)/);
  const token = request.headers.get('cf-access-jwt-assertion') || (cookie && cookie[1]);
  if (!token) return null;
  try {
    const [h, p, s] = token.split('.');
    const header = JSON.parse(b64u(h));
    const claims = JSON.parse(b64u(p));
    if (header.alg !== 'RS256') return null;
    if (Date.now() - certCache.at > 3600_000 || !certCache.keys.some((k) => k.kid === header.kid)) {
      const r = await fetch(`https://${team}/cdn-cgi/access/certs`);
      certCache = { at: Date.now(), keys: (await r.json()).keys || [] };
    }
    const jwk = certCache.keys.find((k) => k.kid === header.kid);
    if (!jwk) return null;
    const key = await crypto.subtle.importKey('jwk', jwk, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
    const ok = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64u(s), new TextEncoder().encode(h + '.' + p));
    const auds = [].concat(claims.aud);
    if (!ok || !auds.some((x) => audsEnv.includes(x)) || claims.iss !== `https://${team}` || !(claims.exp * 1000 > Date.now())) return null;
    return String(claims.email || '').toLowerCase() === owner.toLowerCase() ? claims.email : null;
  } catch {
    return null;
  }
}

function safeEq(a, b) {
  const x = Buffer.from(String(a)), y = Buffer.from(String(b));
  return x.length === y.length && timingSafeEqual(x, y);
}

/** Провайдеры из данных + значения из secrets.json (секреты маской). */
function publicProviders(providers, secrets) {
  return providers.map((p) => ({
    ...p,
    values: Object.fromEntries((p.fields || []).map((f) => {
      const v = (secrets[p.id] || {})[f.key];
      return [f.key, f.type === 'secret' ? (v ? MASK : '') : v ?? ''];
    })),
  }));
}

async function paypalCheck(v) {
  if (!v.client_id || !v.secret) return { ok: false, error: 'Client ID и Secret не заданы' };
  const host = v.mode === 'sandbox' ? 'https://api-m.sandbox.paypal.com' : 'https://api-m.paypal.com';
  try {
    const r = await fetch(host + '/v1/oauth2/token', {
      method: 'POST',
      headers: { authorization: 'Basic ' + Buffer.from(v.client_id + ':' + v.secret).toString('base64'), 'content-type': 'application/x-www-form-urlencoded' },
      body: 'grant_type=client_credentials',
    });
    const j = await r.json().catch(() => ({}));
    return r.ok && j.access_token ? { ok: true, mode: v.mode || 'live' } : { ok: false, error: j.error_description || j.error || 'HTTP ' + r.status };
  } catch (e) {
    return { ok: false, error: String(e.message || e) };
  }
}
const CHECKS = { paypal_oauth: paypalCheck };

export function makeServer({ dataDir, ownerEmail, apiToken, accessTeam, accessAud }) {
  fs.mkdirSync(dataDir, { recursive: true });
  // fail fast: root-owned bind-mount иначе даёт EACCES/500 на первой записи
  try { fs.accessSync(dataDir, fs.constants.W_OK); } catch { throw new Error(`DATA_DIR ${dataDir} не доступен на запись uid ${process.getuid?.()}: chown 1000:1000 на хосте`); }
  const kv = new FileKV(path.join(dataDir, 'kv.json'));
  const secretsFile = path.join(dataDir, 'secrets.json');
  const providers = JSON.parse(fs.readFileSync(PROVIDERS_FILE, 'utf8'));
  const readSecrets = () => (fs.existsSync(secretsFile) ? JSON.parse(fs.readFileSync(secretsFile, 'utf8')) : {});
  const env = { KV: kv };
  const auth = { team: accessTeam, aud: accessAud, owner: ownerEmail };

  async function route(request) {
    const url = new URL(request.url);
    const p = url.pathname.replace(/\/+$/, '') || '/';
    const m = request.method;
    const ctx = (params = {}) => ({ env, request, params });

    if (p === '/healthz') return json({ ok: true });
    if (p === '/' ) return new Response('pay.pxbt.app', { headers: { 'content-type': 'text/plain; charset=utf-8' } });

    // публичное: страница счёта и его API
    let mm;
    if ((mm = p.match(/^\/i\/([A-Za-z0-9]{1,64})$/)) && m === 'GET') return invoicePage.onRequestGet(ctx({ id: mm[1] }));
    if ((mm = p.match(/^\/api\/invoice\/([A-Za-z0-9]{1,64})$/))) {
      const h = { GET: invoiceApi.onRequestGet, POST: invoiceApi.onRequestPost, PUT: invoiceApi.onRequestPut }[m];
      return h ? h(ctx({ id: mm[1] })) : json({ error: 'method' }, 405);
    }

    const isOwner = !!(await accessEmail(request, auth));
    const bearer = (request.headers.get('authorization') || '').replace(/^Bearer /, '');
    if (p === '/api/invoice' && m === 'POST') {
      if (!isOwner && !(apiToken && safeEq(bearer, apiToken))) return json({ error: 'forbidden' }, 403);
      return invoiceCreate.onRequestPost(ctx());
    }

    if (!(p === '/admin' || p.startsWith('/api/admin/') || p.startsWith('/api/claim/'))) return json({ error: 'not found' }, 404);
    if (!isOwner) return json({ error: 'forbidden: Cloudflare Access (email владельца) обязателен' }, 403);

    if (p === '/admin' && m === 'GET') return adminPage.onRequestGet({ env: { ...env, PROVIDERS: publicProviders(providers, readSecrets()) }, request });
    if (p === '/api/admin/config') {
      const h = { GET: adminConfig.onRequestGet, PUT: adminConfig.onRequestPut }[m];
      return h ? h(ctx()) : json({ error: 'method' }, 405);
    }
    if (p === '/api/claim/nonce' && m === 'POST') return claimNonce.onRequestPost(ctx());
    if (p === '/api/claim/verify' && m === 'POST') return claimVerify.onRequestPost(ctx());
    if (p === '/api/admin/providers' && m === 'GET') return json(publicProviders(providers, readSecrets()));
    if ((mm = p.match(/^\/api\/admin\/providers\/([a-z0-9_-]+)(\/check)?$/))) {
      const prov = providers.find((x) => x.id === mm[1] && x.fields);
      if (!prov) return json({ error: 'unknown provider' }, 404);
      const secrets = readSecrets();
      const cur = secrets[prov.id] || {};
      if (mm[2] && m === 'POST') {
        const fn = CHECKS[prov.check];
        return json(fn ? await fn(cur) : { ok: false, error: 'проверка не поддерживается' });
      }
      if (!mm[2] && m === 'PUT') {
        const body = await request.json().catch(() => null);
        if (!body || typeof body !== 'object') return json({ error: 'object required' }, 400);
        for (const f of prov.fields) {
          if (!(f.key in body)) continue;
          const v = String(body[f.key] ?? '').trim().slice(0, 2000);
          if (f.type === 'secret' && (v === '' || v === MASK)) continue; // пусто/маска = оставить прежний
          if (f.type === 'select' && !f.options.includes(v)) return json({ error: `${f.key}: одно из ${f.options.join('/')}` }, 400);
          cur[f.key] = v;
        }
        secrets[prov.id] = cur;
        writeAtomic(secretsFile, JSON.stringify(secrets, null, 1), 0o600);
        return json({ ok: true, values: publicProviders([prov], secrets)[0].values });
      }
      return json({ error: 'method' }, 405);
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
  srv.reloadKV = () => kv.load();
  return srv;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const e = process.env;
  const srv = makeServer({
    dataDir: e.DATA_DIR || '/data',
    ownerEmail: e.OWNER_EMAIL,
    apiToken: e.PAY_API_TOKEN,
    accessTeam: e.CF_ACCESS_TEAM_DOMAIN,
    accessAud: e.CF_ACCESS_AUD,
  });
  srv.listen(Number(e.PORT || 8080), '0.0.0.0', () => console.log('pay.pxbt.app listening on', e.PORT || 8080));
}
