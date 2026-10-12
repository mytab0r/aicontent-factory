#!/usr/bin/env python3
"""recheck_blockers.py — перепроверка blocked-карточек kanban и авто-unblock с доказательством.

Конвенция: в теле blocked-карточки есть строки вида `needs: <тип>:<значение>`.
Типы: secret, file, service, url, pr, other. other — машинно непроверяемо.
Все needs выполнены (и нет other/unknown) → карточка в ready (или done при
`on_resolve: complete` в теле) + комментарий-доказательство. Иначе — не трогаем,
КРОМЕ случая «решено в комментарии»: после последнего события blocked есть
комментарий «блокер снят» / «UNBLOCK-решение» — снимаем так же (ready/done по
on_resolve; явный fail в needs сильнее комментария). Снятие пишет task_events
(unblocked/completed) и чистит block_kind/block_recurrences.

`ck_url` не следует редиректам: 3xx (CF Access/SSO) = fail.

Только stdlib. Запуск:
  python3 recheck_blockers.py --dry-run            # отчёт без записи в БД
  python3 recheck_blockers.py                      # боевой прогон по одной доске
  python3 recheck_blockers.py --db PATH --report-dir DIR
  python3 recheck_blockers.py --selftest           # assert-самотест на временной БД
"""
import argparse
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

NEEDS_RE = re.compile(r"^\s*needs:\s*(secret|file|service|url|pr|other)\s*:\s*(.+?)\s*$", re.M)
ON_RESOLVE_RE = re.compile(r"^\s*on_resolve:\s*complete\s*$", re.M)
# решение о снятии, записанное комментарием ПОСЛЕ последнего события blocked
UNBLOCK_RE = re.compile(r"блокер снят|UNBLOCK-решение|вопрос снят", re.I)
PR_RE = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")
GH_TOKEN_FILE = "/opt/data/secrets/github_token"

# ponytail: прямой UPDATE/INSERT в sqlite вместо kanban-API — скрипт живёт рядом с БД
# (cron-задача из sibling-карточки); при переезде БД добавить hermes-CLI-бэкенд.


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 3xx не идём за редиректом — вернётся HTTPError с кодом 3xx


_OPENER = urllib.request.build_opener(_NoRedirect)


def ck_secret(value):
    missing = [n.strip() for n in value.split(",") if n.strip() and n.strip() not in os.environ]
    if missing:
        return "fail", "нет в окружении: " + ", ".join(missing)  # значения не логируем никогда
    return "ok", "имя(имена) присутствуют в окружении"


def ck_file(value):
    return ("ok", "файл существует") if os.path.exists(value) else ("fail", "файл отсутствует")


def ck_service(value):
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        return "unknown", "формат service: host:port"
    try:
        with socket.create_connection((host, int(port)), timeout=5):
            return "ok", f"TCP {host}:{port} принимается"
    except OSError as e:
        return "fail", f"TCP {host}:{port} недоступен: {e.__class__.__name__}"


def ck_url(value):
    headers = {"User-Agent": "recheck_blockers/1"}
    if urllib.parse.urlsplit(value).netloc == "api.github.com":
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token and os.path.exists(GH_TOKEN_FILE):
            token = open(GH_TOKEN_FILE).read().strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"  # как _pr_api: приватные репо без токена = 404
    req = urllib.request.Request(value, headers=headers)
    try:
        with _OPENER.open(req, timeout=10) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code  # в т.ч. 3xx: редирект на CF Access/SSO трактуем как fail
    except (urllib.error.URLError, OSError, ValueError) as e:
        return "unknown", f"недоступен: {e.__class__.__name__}"
    if 200 <= code < 300:
        return "ok", f"HTTP {code}"
    if 300 <= code < 400:
        return "fail", f"HTTP {code} redirect (за редиректами не ходим — CF Access/SSO не «ok»)"
    return "fail", f"HTTP {code}"


def _pr_api(owner, repo, num):
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token and os.path.exists(GH_TOKEN_FILE):
        token = open(GH_TOKEN_FILE).read().strip()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{num}",
        headers={"User-Agent": "recheck_blockers/1", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.load(r)
    return bool(d.get("merged")), d.get("state")


def ck_pr(value):
    m = PR_RE.match(value)
    if not m:
        return "unknown", "формат pr: владелец/репо#N"
    owner, repo, num = m.groups()
    try:
        out = subprocess.run(
            ["gh", "pr", "view", num, "-R", f"{owner}/{repo}", "--json", "state,merged"],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode == 0:
            d = json.loads(out.stdout)
            return ("ok", "PR смержен") if d.get("merged") else ("fail", f"state={d.get('state')}, merged=false")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # gh нет/завис — пробуем API
    try:
        merged, state = _pr_api(owner, repo, num)
        return ("ok", "PR смержен") if merged else ("fail", f"state={state}, merged=false")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "fail", "PR не найден"
        return "unknown", f"GitHub API HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError):
        return "unknown", "gh и GitHub API недоступны"


CHECKS = {"secret": ck_secret, "file": ck_file, "service": ck_service, "url": ck_url, "pr": ck_pr}


def evaluate(body):
    """→ (вердикт, строки-доказательства). Вердикт: resolve|blocked|unverifiable|no_needs.
    Каждая проверка вызывается ровно один раз."""
    found = NEEDS_RE.findall(body)
    if not found:
        return "no_needs", ["в теле нет строк needs:"]
    lines, states, has_other = [], [], False
    for typ, value in found:
        if typ == "other":
            has_other = True
            lines.append(f"- needs: other:{value} → непроверяемо (other)")
            continue
        state, detail = CHECKS[typ](value)
        states.append(state)
        lines.append(f"- needs: {typ}:{value} → {state}: {detail}")
    if has_other or "unknown" in states:
        return "unverifiable", lines
    if "fail" in states:
        return "blocked", lines
    return "resolve", lines


def _resolved_in_comment(c, tid):
    """True, если после последнего события blocked есть комментарий «блокер снят»/«UNBLOCK-решение»."""
    ev = c.execute(
        "select created_at from task_events where task_id=? and kind='blocked' order by id desc limit 1",
        (tid,),
    ).fetchone()
    if not ev:
        return False
    row = c.execute(
        "select body from task_comments where task_id=? and created_at>=? order by id desc limit 1",
        (tid, ev[0]),
    ).fetchone()
    if not row:
        return False
    return bool(UNBLOCK_RE.search(row[0])) and not re.search(r"держать в blocked|остаётся в blocked|остаётся blocked", row[0], re.I)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lift(c, tid, new_status, dry_run, lines, via):
    """Снятие блокера: статус + блокирующие поля в нейтраль + комментарий + task_events."""
    proof = (
        f"recheck_blockers: блокер снят автоматически ({now_iso()}, dry_run={dry_run}, via={via}).\n"
        + "Проверки:\n" + "\n".join(lines)
    )
    if dry_run:
        return proof
    ts = int(time.time())
    payload = json.dumps({"summary": "recheck_blockers: снято (" + via + ")", "by": "recheck_blockers"}, ensure_ascii=False)
    with c:
        if new_status == "done":
            c.execute(
                "update tasks set status='done', block_kind=null, block_recurrences=null,"
                " claim_lock=null, claim_expires=null, completed_at=? where id=?",
                (ts, tid),
            )
            c.execute("insert into task_events (task_id, kind, payload, created_at) values (?,?,?,?)",
                      (tid, "completed", payload, ts))
        else:
            c.execute(
                "update tasks set status='ready', block_kind=null, block_recurrences=null,"
                " claim_lock=null, claim_expires=null where id=?",
                (tid,),
            )
            c.execute("insert into task_events (task_id, kind, payload, created_at) values (?,?,?,?)",
                      (tid, "unblocked", json.dumps({"status": "ready", "resume_status": "ready",
                                                     "by": "recheck_blockers", "via": via}, ensure_ascii=False), ts))
        c.execute("insert into task_comments (task_id, author, body, created_at) values (?,?,?,?)",
                  (tid, "recheck_blockers", proof, ts))
    return proof


def run(db_path, dry_run, report_dir):
    c = sqlite3.connect(db_path)
    cards = c.execute("select id, title, body from tasks where status='blocked' order by id").fetchall()
    sections = {"resolve": [], "comment": [], "blocked": [], "unverifiable": [], "no_needs": []}
    for tid, title, body in cards:
        verdict, lines = evaluate(body or "")
        via = "needs"
        if verdict in ("no_needs", "unverifiable") and _resolved_in_comment(c, tid):
            verdict, via = "comment", "comment"
            lines.append("- после последнего blocked есть комментарий «блокер снят»/«UNBLOCK-решение» → снимаем")
        new_status = "done" if verdict in ("resolve", "comment") and ON_RESOLVE_RE.search(body or "") else "ready"
        if verdict in ("comment", "resolve"):
            sections[verdict].append((tid, title, lines))
            _lift(c, tid, new_status, dry_run, lines, via)
            suffix = f"- → {new_status}" + (" (dry-run, БД не менялась)" if dry_run else "")
            sections[verdict][-1] = (tid, title, lines + [suffix])
        else:
            sections[verdict].append((tid, title, lines))
    c.close()

    rep = [f"# Отчёт перепроверки блокеров — {now_iso()}" + (" (dry-run)" if dry_run else ""), ""]
    titles = {"resolve": "Снято (needs выполнены)",
              "comment": "Решено в комментарии (после blocked)",
              "blocked": "Всё ещё заблокировано (с причиной)",
              "unverifiable": "Непроверяемо (other/unknown)",
              "no_needs": "Без needs-строк (конвенция не соблюдена)"}
    for key in ("resolve", "comment", "blocked", "unverifiable", "no_needs"):
        rep.append(f"## {titles[key]} ({len(sections[key])})")
        for tid, title, lines in sections[key]:
            rep.append(f"- {tid} «{title}»")
            rep.extend("  " + l for l in lines)
        rep.append("")
    text = "\n".join(rep)
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, f"blockers-report-{datetime.now(timezone.utc):%Y-%m-%d}.md")
    with open(path, "w") as f:
        f.write(text)
    print(text)
    print(f"отчёт: {path}")
    return 0


def _selftest_db(tmp, ok_file):
    db = os.path.join(tmp, "t.db")
    c = sqlite3.connect(db)
    c.executescript(
        "create table tasks (id text primary key, title text, body text, status text,"
        " block_kind text, block_recurrences integer, claim_lock text, claim_expires integer,"
        " completed_at integer);"
        "create table task_comments (id integer primary key autoincrement, task_id text,"
        " author text, body text, created_at integer);"
        "create table task_events (id integer primary key autoincrement, task_id text,"
        " run_id integer, kind text, payload text, created_at integer);"
    )
    t0 = int(time.time()) - 100
    c.executemany(
        "insert into tasks (id,title,body,status,block_kind,completed_at) values (?,?,?,?,?,?)",
        [
            ("t_ok", "решённая", f"needs: file:{ok_file}\non_resolve: complete", "blocked", "transient", None),
            ("t_no", "нерешённая", f"needs: file:{tmp}/missing.txt", "blocked", "transient", None),
            ("t_other", "непроверяемая", "needs: other: решение владельца", "blocked", "needs_input", None),
            ("t_cmt", "решено комментарием", "без needs", "blocked", "needs_input", None),
            ("t_cmt_done", "комментарий+on_resolve", "on_resolve: complete", "blocked", "transient", None),
            ("t_cmt_fail", "комментарий против fail", f"needs: file:{tmp}/missing.txt", "blocked", "transient", None),
            ("t_cmt_hold", "комментарий с удержанием", "без needs", "blocked", "transient", None),
        ],
    )
    for tid in ("t_cmt", "t_cmt_done", "t_cmt_fail", "t_cmt_hold"):
        c.execute("insert into task_events (task_id, kind, created_at) values (?,?,?)", (tid, "blocked", t0))
    c.executemany(
        "insert into task_comments (task_id, author, body, created_at) values (?,?,?,?)",
        [
            ("t_cmt", "default", "блокер снят: ревью принято", t0 + 10),
            ("t_cmt_done", "default", "UNBLOCK-решение: принято", t0 + 10),
            ("t_cmt_fail", "default", "блокер снят", t0 + 10),
            ("t_cmt_fail", "default", "блокер снят (старый, до блокировки)", t0 - 10),
            ("t_cmt_hold", "default", "блокер снят, но карточку держать в blocked до вердикта", t0 + 10),
        ],
    )
    c.commit()
    c.close()
    return db


def selftest():
    tmp = tempfile.mkdtemp(prefix="recheck-selftest-")

    # --- ck_url: редирект = fail, прямой 200 = ok (локальный HTTP-сервер, без интернета) ---
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/r":
                self.send_response(302)
                self.send_header("Location", "/final")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    st, detail = ck_url(f"http://127.0.0.1:{port}/r")
    assert st == "fail" and "302" in detail, (st, detail)
    st, detail = ck_url(f"http://127.0.0.1:{port}/direct")
    assert st == "ok", (st, detail)
    srv.shutdown()

    # --- evaluate: одна проверка на need ---
    ok_file = os.path.join(tmp, "exists.txt")
    open(ok_file, "w").write("x")
    calls = []
    orig = CHECKS["file"]
    CHECKS["file"] = lambda v: (calls.append(v), orig(v))[1]
    verdict, _ = evaluate(f"needs: file:{ok_file}")
    CHECKS["file"] = orig
    assert verdict == "resolve" and len(calls) == 1, (verdict, calls)

    # --- снятия на временной БД (needs + комментарий) ---
    db = _selftest_db(tmp, ok_file)
    run(db, dry_run=False, report_dir=tmp)
    c = sqlite3.connect(db)
    st = dict(c.execute("select id, status from tasks"))
    n = c.execute("select count(*) from task_comments where task_id='t_ok'").fetchone()[0]
    ev = dict(c.execute("select task_id, kind from task_events where kind in ('unblocked','completed')"))
    bk = dict(c.execute("select id, block_kind from tasks"))
    br = dict(c.execute("select id, block_recurrences from tasks where id in ('t_cmt','t_ok')"))
    c.close()
    assert st["t_ok"] == "done", st
    assert st["t_no"] == "blocked", st
    assert st["t_other"] == "blocked", st
    assert st["t_cmt"] == "ready", st
    assert st["t_cmt_done"] == "done", st
    assert st["t_cmt_fail"] == "blocked", st  # fail в needs сильнее комментария
    assert st["t_cmt_hold"] == "blocked", st  # «держать в blocked» в комментарии сильнее «снят»
    assert n == 1, n
    assert ev["t_ok"] == "completed" and ev["t_cmt"] == "unblocked" and ev["t_cmt_done"] == "completed", ev
    assert "t_cmt_hold" not in ev and "t_cmt_fail" not in ev, ev
    assert bk["t_cmt"] is None and bk["t_ok"] is None, bk
    assert all(v is None for v in br.values()), br
    print("SELFTEST OK (redirect=fail, одна проверка на need, needs→done+event, "
          "комментарий→ready/done+event, fail сильнее комментария, комментарий до blocked не считается)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.environ.get("HERMES_KANBAN_DB",
                    "/opt/data/kanban/boards/aicontent-factory/kanban.db"))
    ap.add_argument("--report-dir", default=".")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not os.path.exists(args.db):
        print(f"БД не найдена: {args.db}", file=sys.stderr)
        return 2
    return run(args.db, args.dry_run, args.report_dir)


if __name__ == "__main__":
    sys.exit(main())
