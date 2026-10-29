#!/usr/bin/env python3
"""t_1b6fdb47: deploy/pay-page/deploy_verify.sh на фейковом healthz+Telegram.
1) sha совпал -> exit 0, алерта нет. 2) не совпал за TIMEOUT -> exit 1 и ровно один sendMessage с sha.
3) Telegram ответил ok:false -> exit 2 (недоставленный алерт не глотается).
pay-image.yml обязан вызывать именно этот скрипт. Запуск: python3 pipeline/test_pay_deploy_verify.py"""
import http.server, json, os, subprocess, threading
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent.parent
SH = ROOT / "deploy/pay-page/deploy_verify.sh"
STATE = {"sha": "", "tg_ok": True, "sent": []}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body):
        b = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self): self._send({"ok": True, "sha": STATE["sha"]})

    def do_POST(self):
        STATE["sent"].append(parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()))
        self._send({"ok": STATE["tg_ok"]})


def run(sha, tg_ok=True):
    STATE.update(sha=sha, tg_ok=tg_ok, sent=[])
    base = f"http://127.0.0.1:{SRV.server_port}"
    env = dict(os.environ, WANT_SHA="a" * 40, URL=f"{base}/healthz", TIMEOUT="2", INTERVAL="1", TG_API=base,
               TG_BOT_TOKEN="x", TG_CHAT_ID="1", TG_THREAD_ID="2")
    return subprocess.run(["bash", str(SH)], env=env, capture_output=True, text=True, timeout=60).returncode


SRV = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=SRV.serve_forever, daemon=True).start()


def test_match_passes_without_alert():
    assert run("a" * 40) == 0 and not STATE["sent"]


def test_timeout_alerts_once():
    assert run("b" * 40) == 1
    assert len(STATE["sent"]) == 1, STATE["sent"]
    m = STATE["sent"][0]
    assert m["chat_id"] == ["1"] and m["message_thread_id"] == ["2"] and "aaaaaaa" in m["text"][0]


def test_undelivered_alert_fails_loud():
    assert run("b" * 40, tg_ok=False) == 2


def test_workflow_uses_script():
    wf = (ROOT / ".github/workflows/pay-image.yml").read_text(encoding="utf-8")
    assert "deploy/pay-page/deploy_verify.sh" in wf.split("deploy-verify:", 1)[1]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
