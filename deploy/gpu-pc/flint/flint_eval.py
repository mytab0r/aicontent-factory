#!/usr/bin/env python3
"""Flint agentic eval: 5 Hermes/Codex-style tasks (tool calling, file edit, tests). t_2ca44c81
usage: flint_eval.py <base_url> <model> [api_key]  -> per-task JSON lines + SUMMARY line.
Stdlib only. Fresh temp dir per task; tools read_file/write_file/run/finish.
Success checked by code (tests / exact answer / mutants), never by the model's claim."""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error

BASE, MODEL = sys.argv[1].rstrip("/"), sys.argv[2]
KEY = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("EVAL_KEY", "none")
MAX_TURNS, MAX_TOK = 14, int(os.environ.get("EVAL_MAX_TOKENS", "8192"))

def fn(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": {k: {"type": "string"} for k in props}, "required": req}}}
TOOLS = [fn("read_file", "Read a text file from the workspace.", ["path"], ["path"]),
         fn("write_file", "Overwrite a file in the workspace with full content.", ["path", "content"], ["path", "content"]),
         fn("run", "Run a bash command in the workspace (60s timeout). Returns exit code and output.", ["cmd"], ["cmd"]),
         fn("finish", "Call when done. Put the final answer (if the task asks for one) in `answer`.", ["answer"], ["answer"])]

MB_SRC = """import re
def mb(s):
    \"\"\"docker stats size -> MiB. '1.5GiB'->1536, '512MiB'->512, '10kB'->10/1024, '0B'->0, garbage->0\"\"\"
    m = re.match(r"([\\d.]+)\\s*([KMG]i?B)", s.strip())
    num, unit = m.groups()
    mult = {"K": 1/1024, "M": 1, "G": 1024}[unit[0]]
    return float(num) * mult
"""
MB_TEST = """import unittest
from stats import mb
class T(unittest.TestCase):
    def test_units(self):
        self.assertEqual(mb("1.5GiB"), 1536); self.assertEqual(mb("512MiB"), 512)
        self.assertAlmostEqual(mb("10kB"), 10/1024)
    def test_bytes_and_garbage(self):
        self.assertEqual(mb("0B"), 0); self.assertAlmostEqual(mb("2048B"), 2048/1024/1024); self.assertEqual(mb("n/a"), 0)
if __name__ == "__main__": unittest.main()
"""
GATE_SRC = """def gate(free_gb: int, need_gb: int, floor_gb: int) -> bool:
    \"\"\"True if after downloading need_gb at least floor_gb stays free.\"\"\"
    return free_gb - need_gb >= floor_gb
"""
PAGE_SRC = """def paginate(items, page, per_page):
    \"\"\"1-based pages. paginate([1..10], 2, 3) -> [4,5,6]; out-of-range page -> []\"\"\"
    start = page * per_page
    return items[start:start + per_page]

def page_count(n, per_page):
    return n // per_page
"""
PAGE_TEST = """import unittest
from pager import paginate, page_count
class T(unittest.TestCase):
    def test_pages(self):
        xs = list(range(1, 11))
        self.assertEqual(paginate(xs, 1, 3), [1, 2, 3]); self.assertEqual(paginate(xs, 4, 3), [10])
        self.assertEqual(paginate(xs, 5, 3), []); self.assertEqual(paginate(xs, 0, 3), [])
    def test_count(self):
        self.assertEqual(page_count(10, 3), 4); self.assertEqual(page_count(9, 3), 3); self.assertEqual(page_count(0, 3), 0)
if __name__ == "__main__": unittest.main()
"""
CFG = """model:
  default: auto-orchestrator-combo
  provider: 9router
providers:
  9router:
    base_url: https://router.example/v1
    context_length: 200000
fallback_model:
  - provider: 9router
    model: auto-worker-combo
  - provider: 9router
    model: glm/glm-5.3-flash
"""
_EV = [("skipped_global_cap", "t_5f3bd387"), ("spawned", "t_96c0790c"), ("skipped_global_cap", "t_2ca44c81"),
       ("skipped_global_cap", "t_5f3bd387"), ("skipped_assignee", "t_2ca44c81"), ("skipped_global_cap", "t_d1b62ede")]
LOG = "\n".join(f"2026-10-21T{h:02d}:{m:02d}:00Z dispatch: {ev} card={c}" for h in range(10, 14) for m, (ev, c) in enumerate(_EV)) \
    + "\n" + "\n".join(f"2026-10-21T15:{m:02d}:00Z dispatch: skipped_global_cap card=t_2ca44c81" for m in range(5)) + "\n"
# skipped_global_cap: t_5f3bd387=8, t_2ca44c81=4+5=9, t_d1b62ede=4 -> t_2ca44c81 (naive "most lines" gives t_2ca44c81 too, "most at 10-13h" gives t_5f3bd387)


def sh(cmd, cwd, t=60):
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=t)
        return r.returncode, (r.stdout + r.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def check_mutant_killed(d):
    """Model-written test must pass on the real gate and fail on each broken variant."""
    if sh("python3 -m unittest -q test_gate", d)[0] != 0:
        return False
    src = open(f"{d}/gate.py").read()
    try:
        for bad in ("free_gb - need_gb > floor_gb", "free_gb - need_gb >= floor_gb - 1", "free_gb >= floor_gb"):
            open(f"{d}/gate.py", "w").write(GATE_SRC.replace("free_gb - need_gb >= floor_gb", bad, 1))
            if sh("python3 -m unittest -q test_gate", d)[0] == 0:
                return False
        return True
    finally:
        open(f"{d}/gate.py", "w").write(src)


TASKS = [
    {"id": "T1-tool-read", "kind": "tool calling", "files": {"config.yaml": CFG},
     "prompt": "In config.yaml, what is the model name of the LAST entry in fallback_model? Read the file, then call finish with just the model name.",
     "check": lambda d, ans: (ans or "").strip().strip("`'\"") == "glm/glm-5.3-flash"},
    {"id": "T2-fix-parser", "kind": "file edit + test", "files": {"stats.py": MB_SRC, "test_stats.py": MB_TEST},
     "prompt": "stats.mb() crashes on inputs like '0B' and 'n/a' (AttributeError on None.groups()). Fix stats.py so `python3 -m unittest -q test_stats` passes. Do not edit the test. Run the tests, then call finish.",
     "check": lambda d, ans: sh("python3 -m unittest -q test_stats", d)[0] == 0 and open(f"{d}/test_stats.py").read() == MB_TEST},
    {"id": "T3-write-test", "kind": "write test", "files": {"gate.py": GATE_SRC},
     "prompt": "Write test_gate.py (unittest) for gate.gate(). Cover: download allowed when exactly floor remains, refused when one GB less remains, refused when free < need. Run it with `python3 -m unittest -q test_gate`, then call finish.",
     "check": lambda d, ans: os.path.exists(f"{d}/test_gate.py") and check_mutant_killed(d)},
    {"id": "T4-log-shell", "kind": "tool calling (shell)", "files": {"dispatch.log": LOG},
     "prompt": "dispatch.log has dispatcher events. Which card id has the most `skipped_global_cap` events? Use shell tools to count, then call finish with just the card id.",
     "check": lambda d, ans: "t_2ca44c81" in (ans or "") and "t_5f3bd387" not in (ans or "")},
    {"id": "T5-bugfix-run-tests", "kind": "file edit + test", "files": {"pager.py": PAGE_SRC, "test_pager.py": PAGE_TEST},
     "prompt": "test_pager.py fails. Find and fix the bugs in pager.py (do not change the tests). Verify with `python3 -m unittest -q test_pager`, then call finish.",
     "check": lambda d, ans: sh("python3 -m unittest -q test_pager", d)[0] == 0 and open(f"{d}/test_pager.py").read() == PAGE_TEST},
]


def chat(messages):
    body = {"model": MODEL, "messages": messages, "tools": TOOLS, "max_tokens": MAX_TOK, "temperature": 1.0, "top_p": 0.95, "stream": False}
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    for att in range(4):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return json.loads(r.read().decode()), time.time() - t0
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503) or att == 3:
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:200]!r}")
            time.sleep(20 * (att + 1))
        except (ConnectionError, urllib.error.URLError, TimeoutError) as e:  # transport drop != model failure
            if att == 3:
                raise
            time.sleep(10 * (att + 1))


REQ = {t["function"]["name"]: t["function"]["parameters"]["required"] for t in TOOLS}


def tool(name, args, d):
    miss = [k for k in REQ.get(name, []) if not isinstance(args.get(k), str)]
    if miss:  # like a real agent runtime: schema violation is an error, not a silent default
        return f"error: missing required argument(s) {miss}; schema requires {REQ[name]}"
    p = lambda x: os.path.join(d, os.path.normpath("/" + str(x)).lstrip("/"))  # confined to workspace
    if name == "read_file":
        try:
            return open(p(args["path"])).read()[:8000]
        except Exception as e:
            return f"error: {e}"
    if name == "write_file":
        try:
            os.makedirs(os.path.dirname(p(args["path"])), exist_ok=True)
            open(p(args["path"]), "w").write(args.get("content", ""))
            return "ok"
        except Exception as e:
            return f"error: {e}"
    if name == "run":
        rc, out = sh(args.get("cmd", ""), d)
        return f"exit={rc}\n{out}"
    return "unknown tool"


def run_task(t):
    d = tempfile.mkdtemp(prefix="flint-" + t["id"] + "-")
    for f, c in t["files"].items():
        open(f"{d}/{f}", "w").write(c)
    msgs = [{"role": "system", "content": "You are a coding agent working in a sandbox directory. Use the tools; paths are relative to the workspace. Be concise."},
            {"role": "user", "content": t["prompt"]}]
    ctoks, gen_s, answer, err, turns, tps_srv, schema_errs = 0, 0.0, None, None, 0, [], 0
    try:
        for turns in range(1, MAX_TURNS + 1):
            j, dt = chat(msgs)
            ctoks += (j.get("usage") or {}).get("completion_tokens", 0); gen_s += dt
            if (j.get("timings") or {}).get("predicted_per_second"):
                tps_srv.append(j["timings"]["predicted_per_second"])
            m = j["choices"][0]["message"]
            keep = {"role": "assistant", "content": m.get("content") or ""}
            rc = m.get("reasoning_content") or m.get("reasoning")
            if rc:
                keep["reasoning_content"] = rc  # model card: keep reasoning in history
            calls = m.get("tool_calls") or []
            if calls:
                keep["tool_calls"] = calls
            msgs.append(keep)
            if not calls:
                msgs.append({"role": "user", "content": "Use the tools. Call finish when done."})
                continue
            done = False
            for c in calls:
                name = c["function"]["name"]
                try:
                    a = json.loads(c["function"].get("arguments") or "{}")
                    res = tool(name, a, d) if name != "finish" else "ok"
                    if name != "finish" and res.startswith("error: missing required"):
                        schema_errs += 1
                except json.JSONDecodeError:
                    a, res = {}, "error: arguments are not valid JSON"
                if name == "finish":
                    answer, done = a.get("answer", ""), True
                msgs.append({"role": "tool", "tool_call_id": c.get("id") or name, "content": res})
            if done:
                break
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:300]
    if os.environ.get("EVAL_LOG"):
        os.makedirs(os.environ["EVAL_LOG"], exist_ok=True)
        json.dump(msgs, open(os.path.join(os.environ["EVAL_LOG"], t["id"] + ".json"), "w"), ensure_ascii=False, indent=1)
    ok = bool(answer is not None and t["check"](d, answer))
    return {"task": t["id"], "kind": t["kind"], "success": ok, "finished": answer is not None,
            "answer": (answer or "")[:80], "turns": turns, "schema_errors": schema_errs, "completion_tokens": ctoks, "wall_s": round(gen_s, 1),
            "tok_s_wall": round(ctoks / gen_s, 1) if gen_s else 0,
            "tok_s_server": round(sum(tps_srv) / len(tps_srv), 1) if tps_srv else None, "error": err}


if __name__ == "__main__":
    only = os.environ.get("EVAL_ONLY")
    res = []
    for t in TASKS:
        if only and t["id"] not in only.split(","):
            continue
        r = run_task(t); res.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    n = sum(r["success"] for r in res)
    print("SUMMARY " + json.dumps({"model": MODEL, "passed": n, "total": len(res),
          "success_pct": round(100 * n / len(res)) if res else 0,
          "tok_s_wall_avg": round(sum(r["tok_s_wall"] for r in res) / len(res), 1) if res else 0}), flush=True)
