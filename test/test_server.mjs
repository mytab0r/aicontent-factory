/**
 * Сквозные тесты контейнерного сервера pay.pxbt.app (deploy/pay-page/server.mjs):
 * доступ к админке (CF Access email), провайдеры из данных, секреты в файле 600 с маской,
 * проверка PayPal (fetch застаблен), инвойс видит только включённые пары.
 * Запуск: node test/test_server.mjs
 */
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { generateKeyPairSync, createSign } from 'node:crypto';
import { makeServer } from '../deploy/pay-page/server.mjs';

// Cloudflare Access: настоящий RS256 JWT, ключи команды застаблены
const TEAM = 'team.cloudflareaccess.com', AUD = 'aud-tag';
const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const JWK = { ...publicKey.export({ format: 'jwk' }), kid: 'k1', alg: 'RS256' };
function jwt(claims, kid = 'k1', key = privateKey) {
  const enc = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
  const hp = enc({ alg: 'RS256', kid }) + '.' + enc(claims);
  return hp + '.' + createSign('RSA-SHA256').update(hp).sign(key).toString('base64url');
}
const claims = (email, extra = {}) => ({ email, aud: [AUD], iss: 'https://' + TEAM, exp: Math.floor(Date.now() / 1000) + 600, ...extra });

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pay-'));
const OWNER = 'owner@example.com';
const srv = makeServer({ dataDir: dir, ownerEmail: OWNER, apiToken: 'tok123', accessTeam: TEAM, accessAud: AUD, proxySecret: 'sso-secret-123' });
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const base = 'http://127.0.0.1:' + srv.address().port;

const realFetch = globalThis.fetch;
const paypalCalls = [];
globalThis.fetch = async (url, init) => {
  if (String(url) === `https://${TEAM}/cdn-cgi/access/certs`) return new Response(JSON.stringify({ keys: [JWK] }));
  if (String(url).includes('paypal.com')) {
    paypalCalls.push({ url: String(url), auth: init.headers.authorization });
    const ok = init.headers.authorization === 'Basic ' + Buffer.from('cid:good').toString('base64');
    return new Response(JSON.stringify(ok ? { access_token: 'x' } : { error: 'invalid_client' }), { status: ok ? 200 : 401 });
  }
  return realFetch(url, init);
};
const owner = { 'cf-access-jwt-assertion': jwt(claims(OWNER)), 'content-type': 'application/json' };
const H = (t) => ({ 'cf-access-jwt-assertion': t });
const req = (p, init = {}) => realFetch(base + p, init);

try {
  // доступ: без JWT, чужой email, просроченный, чужой aud, поддельная подпись, голый email-заголовок -> 403
  assert.strictEqual((await req('/admin')).status, 403);
  assert.strictEqual((await req('/admin', { headers: { 'cf-access-authenticated-user-email': OWNER } })).status, 403, 'email-заголовок без JWT не пускает');
  assert.strictEqual((await req('/api/admin/config', { headers: H(jwt(claims('x@y.z'))) })).status, 403);
  assert.strictEqual((await req('/admin', { headers: H(jwt(claims(OWNER, { exp: 1 }))) })).status, 403, 'exp');
  assert.strictEqual((await req('/admin', { headers: H(jwt(claims(OWNER, { aud: ['other'] }))) })).status, 403, 'aud');
  const evil = generateKeyPairSync('rsa', { modulusLength: 2048 }).privateKey;
  assert.strictEqual((await req('/admin', { headers: H(jwt(claims(OWNER), 'k1', evil)) })).status, 403, 'подпись');
  assert.strictEqual((await req('/admin', { headers: { cookie: 'CF_Authorization=' + jwt(claims(OWNER)) } })).status, 200, 'cookie CF_Authorization');
  assert.strictEqual((await req('/api/claim/nonce', { method: 'POST', body: '{"chain":"evm"}' })).status, 403);
  // Zoraxy SSO: верный секрет пускает, неверный/пустой нет
  assert.strictEqual((await req('/admin', { headers: { 'x-pay-proxy-auth': 'sso-secret-123' } })).status, 200, 'sso ok');
  assert.strictEqual((await req('/admin', { headers: { 'x-pay-proxy-auth': 'wrong' } })).status, 403, 'sso wrong');
  assert.strictEqual((await req('/admin', { headers: { 'x-pay-proxy-auth': '' } })).status, 403, 'sso empty');
  const adm = await req('/admin', { headers: owner });
  assert.strictEqual(adm.status, 200);
  assert.match(await adm.text(), /PayPal/, 'админка рендерит провайдеров из данных');

  // провайдеры описаны данными
  let pv = await (await req('/api/admin/providers', { headers: owner })).json();
  const pp = pv.find((p) => p.id === 'paypal');
  assert.deepStrictEqual(pp.fields.map((f) => f.key), ['client_id', 'secret', 'mode']);

  // сохранение: секрет в файле 600, наружу только маска
  let r = await req('/api/admin/providers/paypal', { method: 'PUT', headers: owner, body: JSON.stringify({ client_id: 'cid', secret: 'good', mode: 'sandbox' }) });
  assert.strictEqual(r.status, 200);
  const sf = path.join(dir, 'secrets.json');
  assert.strictEqual(fs.statSync(sf).mode & 0o777, 0o600, 'secrets.json chmod 600');
  assert.strictEqual(JSON.parse(fs.readFileSync(sf, 'utf8')).paypal.secret, 'good');
  pv = await (await req('/api/admin/providers', { headers: owner })).json();
  const vals = pv.find((p) => p.id === 'paypal').values;
  assert.strictEqual(vals.client_id, 'cid');
  assert.strictEqual(vals.mode, 'sandbox');
  assert.ok(!JSON.stringify(pv).includes('good'), 'секрет не отдаётся назад');
  assert.match(vals.secret, /^•+$|^•+.{0,4}$/);

  // пустой секрет при повторном сохранении = оставить прежний
  await req('/api/admin/providers/paypal', { method: 'PUT', headers: owner, body: JSON.stringify({ client_id: 'cid', secret: '', mode: 'sandbox' }) });
  assert.strictEqual(JSON.parse(fs.readFileSync(sf, 'utf8')).paypal.secret, 'good');

  // кнопка «проверить»: OAuth token к sandbox
  let c = await (await req('/api/admin/providers/paypal/check', { method: 'POST', headers: owner })).json();
  assert.strictEqual(c.ok, true, JSON.stringify(c));
  assert.strictEqual(paypalCalls.at(-1).url, 'https://api-m.sandbox.paypal.com/v1/oauth2/token');
  await req('/api/admin/providers/paypal', { method: 'PUT', headers: owner, body: JSON.stringify({ secret: 'bad', mode: 'live' }) });
  c = await (await req('/api/admin/providers/paypal/check', { method: 'POST', headers: owner })).json();
  assert.strictEqual(c.ok, false);
  assert.strictEqual(paypalCalls.at(-1).url, 'https://api-m.paypal.com/v1/oauth2/token');

  // инвойс: создать можно владельцу или по bearer-токену бота, анониму нельзя
  assert.strictEqual((await req('/api/invoice', { method: 'POST', body: '{"amount":1}' })).status, 403);
  // Zoraxy шлёт SSO-заголовок и на публичные исключения (/api/invoice): он не даёт права создавать счёт
  assert.strictEqual((await req('/api/invoice', { method: 'POST', headers: { 'x-pay-proxy-auth': 'sso-secret-123' }, body: '{"amount":1}' })).status, 403, 'sso-заголовок на публичном пути');
  r = await req('/api/invoice', { method: 'POST', headers: { authorization: 'Bearer tok123' }, body: JSON.stringify({ amount: 1, memo: '<script>alert(1)</script>' }) });
  assert.strictEqual(r.status, 200);
  const { id, url } = await r.json();
  assert.strictEqual(url, '/i/' + id);

  // клиент видит только включённые пары (адрес пишем в KV как после подписи)
  const kv = JSON.parse(fs.readFileSync(path.join(dir, 'kv.json'), 'utf8'));
  kv.config = { v: JSON.stringify({ addresses: { tron: 'TQrY8try6YCHAEuZGB9puHKiQWy6iRfnCw', evm: '0xabc' }, pairs: {} }) };
  fs.writeFileSync(path.join(dir, 'kv.json'), JSON.stringify(kv));
  srv.reloadKV();
  await req('/api/admin/config', { method: 'PUT', headers: owner, body: JSON.stringify({ pairs: { 'USDT-TRC20': true } }) });
  const inv = await (await req('/api/invoice/' + id)).json();
  assert.deepStrictEqual(inv.pairs.map((p) => p.id), ['USDT-TRC20']);
  const page = await (await req('/i/' + id)).text();
  assert.match(page, /TQrY8try6YCHAEuZGB9puHKiQWy6iRfnCw/);
  assert.ok(!page.includes('USDT-ERC20'), 'выключенная пара не видна');
  assert.ok(!page.includes('<script>alert(1)'), 'memo экранирован');
  assert.strictEqual((await req('/i/nope')).status, 404);
  assert.strictEqual((await req('/healthz')).status, 200);
} finally {
  srv.close();
  globalThis.fetch = realFetch;
}
console.log('server tests: all OK');
