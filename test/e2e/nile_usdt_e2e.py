"""
e2e pay.pxbt.app на Tron Nile testnet: счёт -> перевод USDT-TRC20 -> paid. В CI не запускается (сеть + ключ).

Поднимает настоящий deploy/pay-page/server.mjs, создаёт счёт через /api/invoice, переводит ровно
сумму счёта с тестового кошелька, ждёт PUT /api/invoice/<id> == paid. Результат: JSON в --out.

env (все обязательны, кроме PAY_TRON_API; ключ только из env/secrets, в репо не коммитить):
  NILE_PAYER_PRIVKEY       hex приватный ключ тестового плательщика (TRX на газ + тестовые USDT с фаусета)
  PAY_NILE_RECEIVER        адрес получателя (адрес «владельца» в конфиге pay)
  PAY_USDT_TRC20_CONTRACT  контракт USDT на Nile (TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf на 2026-10)
  PAY_TRON_API             Tronscan API Nile, по умолчанию https://nileapi.tronscan.org

Запуск: set -a; . /opt/data/secrets/pay-nile-test.env; set +a
        uv run --with tronpy python test/e2e/nile_usdt_e2e.py --out nile_e2e.json
"""
import argparse, json, os, secrets, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

from tronpy import Tron
from tronpy.keys import PrivateKey

ROOT = Path(__file__).resolve().parents[2]


def http(method, url, body=None, token=None):
    h = {'content-type': 'application/json'}
    if token:
        h['authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='nile_e2e.json')
    ap.add_argument('--amount', type=float, default=1.0)
    ap.add_argument('--timeout', type=int, default=900)
    a = ap.parse_args()

    env = os.environ
    key = PrivateKey(bytes.fromhex(env['NILE_PAYER_PRIVKEY']))
    receiver, token = env['PAY_NILE_RECEIVER'], env['PAY_USDT_TRC20_CONTRACT']
    env.setdefault('PAY_TRON_API', 'https://nileapi.tronscan.org')
    payer = key.public_key.to_base58check_address()

    data = Path(tempfile.mkdtemp(prefix='pay-nile-'))
    kv = {'config': {'v': json.dumps({'addresses': {'tron': receiver}, 'pairs': {'USDT-TRC20': True}})}}
    (data / 'kv.json').write_text(json.dumps(kv))
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    api_token = secrets.token_hex(16)
    srv = subprocess.Popen(['node', 'deploy/pay-page/server.mjs'], cwd=ROOT,
                           env={**env, 'PORT': str(port), 'DATA_DIR': str(data), 'PAY_API_TOKEN': api_token})
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try:
                if http('GET', base + '/healthz').get('ok'): break
            except OSError:
                time.sleep(0.2)
        inv_id = http('POST', base + '/api/invoice', {'amount': a.amount, 'memo': 'nile e2e'}, api_token)['id']
        sel = http('POST', f'{base}/api/invoice/{inv_id}', {'pair': 'USDT-TRC20'})
        assert sel.get('ok') and sel['pair']['token'] == token and sel['pair']['address'] == receiver, sel
        due = json.loads(json.loads((data / 'kv.json').read_text())['invoice:' + inv_id]['v'])['dueMicro']
        print('invoice', inv_id, 'due', due, 'payer', payer, '->', receiver, flush=True)

        client = Tron(network='nile')
        usdt = client.get_contract(token)
        bal = usdt.functions.balanceOf(payer)
        assert bal >= int(due), f'мало тестовых USDT на {payer}: {bal} < {due}'
        txn = (usdt.functions.transfer(receiver, int(due)).with_owner(payer).fee_limit(100_000_000).build().sign(key))
        res = txn.broadcast().wait(timeout=120)
        tx = txn.txid
        assert res.get('receipt', {}).get('result') == 'SUCCESS', res
        print('tx', tx, flush=True)

        t0, st = time.time(), {}
        while time.time() - t0 < a.timeout:
            st = http('PUT', f'{base}/api/invoice/{inv_id}')
            if st.get('status') == 'paid': break
            time.sleep(10)
        raw = json.loads(json.loads((data / 'kv.json').read_text())['invoice:' + inv_id]['v'])
        out = {'network': 'nile', 'tx': tx, 'tronscan': f'https://nile.tronscan.org/#/transaction/{tx}', 'payer': payer,
               'receiver': receiver, 'usdt_contract': token, 'invoice_id': inv_id, 'status_response': st,
               'invoice_public': http('GET', f'{base}/api/invoice/{inv_id}'), 'invoice_stored': raw,
               'seconds_to_paid': round(time.time() - t0)}
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
        print(json.dumps(st))
        ok = st.get('status') == 'paid' and st.get('tx') == tx and raw.get('status') == 'paid'
        print('METRIC=%d' % ok)
        return 0 if ok else 1
    finally:
        srv.terminate()


if __name__ == '__main__':
    sys.exit(main())
