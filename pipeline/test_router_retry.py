"""router_post: оборванный ответ (IncompleteRead) = сетевой сбой, повторяем (выпуск 15.10 упал на 02 cover)."""
import http.server, os, socket, sys, threading
sys.path.insert(0, os.path.dirname(__file__))
os.environ["ROUTER_API_KEY"] = "x"
hits = []
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        hits.append(1)
        self.send_response(200); self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
        if len(hits) == 1:  # обрыв посреди чанка
            self.wfile.write(b"100\r\n{\"ok\""); self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR); return
        b = b'{"ok": 1}'; self.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(b), b))
srv = http.server.ThreadingHTTPServer(("", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["ROUTER_BASE_URL"] = "http://" + socket.gethostname() + f":{srv.server_address[1]}"
import common
common.time.sleep = lambda s: None
assert common.router_post("/x", {}) == {"ok": 1}, "ожидали успех со 2-й попытки"
assert len(hits) == 2, hits
print("test_router_retry OK")
