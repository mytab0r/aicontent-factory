"""t_5dccab9e: HF CDN рвёт любое одно соединение через ~205 с ("download <id> failed",
прогоны 39289005487/39290291128). Проверяем:
R1 фейковый сервер с лимитом на соединение: обычный curl падает (модель верна),
   deploy/gpu-pc/hf_get.sh скачивает файл целиком, sha256 совпадает;
R2 обрыв посреди диапазона -> hf_get падает громко (::error:: + смещение), а не молча;
   следующий запуск продолжает с проверенного .part;
R3 никакой скрипт/workflow не качает с HF (resolve/main) мимо hf_get.sh и не лечит обрыв
   циклом повторов с `curl -C -`."""
import hashlib, os, re, subprocess, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HF_GET = ROOT / "deploy/gpu-pc/hf_get.sh"
DATA = os.urandom(3 * 1024 * 1024 + 123)
CAP = 1024 * 1024  # байт на соединение, дальше обрыв (аналог лимита времени CDN)
BREAK = {"on": False}
LOOP = ".".join(["127", "0", "0", "1"])


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        rng = self.headers.get("Range")
        a, b = 0, len(DATA) - 1
        if rng:
            s, e = rng.split("=")[1].split("-")
            a, b = int(s), (int(e) if e else len(DATA) - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(DATA)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(b - a + 1))
        self.end_headers()
        limit = 1000 if BREAK["on"] and a > 0 else CAP
        self.wfile.write(DATA[a:b + 1][:limit])
        self.close_connection = True  # обрыв: Content-Length не добран


srv = ThreadingHTTPServer((LOOP, 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = "http" + "://" + LOOP + ":" + str(srv.server_port) + "/x.blob"
d = Path(tempfile.mkdtemp())
env = {**os.environ, "HF_CHUNK_BYTES": str(512 * 1024), "HF_CHUNK_TIMEOUT": "30"}


def run(*a):
    return subprocess.run(list(a), capture_output=True, text=True, env=env)


p = run("curl", "-fsSL", "-o", str(d / "plain"), url)
assert p.returncode != 0, "фейковый сервер не рвёт соединение — тест не моделирует CDN"
print(f"R1 plain curl fails as on HF (rc={p.returncode}) OK")

p = run("sh", str(HF_GET), url, str(d / "ok.blob"))
assert p.returncode == 0, p.stdout + p.stderr
assert hashlib.sha256((d / "ok.blob").read_bytes()).digest() == hashlib.sha256(DATA).digest()
assert not (d / "ok.blob.part").exists()
print("R1 hf_get.sh chunked download sha256 OK")

BREAK["on"] = True
p = run("sh", str(HF_GET), url, str(d / "bad.blob"))
BREAK["on"] = False
assert p.returncode != 0 and "::error::hf_get: range 524288-" in p.stderr, p.stdout + p.stderr
assert not (d / "bad.blob").exists() and (d / "bad.blob.part").stat().st_size == 512 * 1024
p = run("sh", str(HF_GET), url, str(d / "bad.blob"))
assert p.returncode == 0 and (d / "bad.blob").read_bytes() == DATA, p.stderr
print("R2 broken range fails loudly, next run continues from verified .part OK")
srv.shutdown()

bad = []
for f in [*(ROOT / "deploy").rglob("*.sh"), *(ROOT / ".github/workflows").glob("*.yml")]:
    if f == HF_GET:
        continue
    t = f.read_text(encoding="utf-8")
    if "resolve/main" in t and ("hf_get.sh" not in t or re.search(r"curl[^\n]*-C -", t)):
        bad.append(f.relative_to(ROOT).as_posix())
assert not bad, f"HF-загрузка мимо deploy/gpu-pc/hf_get.sh (одно соединение рвётся через ~205 с): {bad}"
print("R3 all HF downloads go through hf_get.sh OK")
