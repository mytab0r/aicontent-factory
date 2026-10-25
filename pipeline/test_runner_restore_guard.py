"""t_b1429246 / t_98562d0e: job killed by runner transport failure often has NO log
blob (BlobNotFound), so the ci.yml runner-restore guard skipped it ("can't confirm
signature") and the run stayed red with a fake verdict. The guard must treat
"failure + log unavailable + frozen in_progress step" as the same transport
signature and rerun the job. A real test failure uploads logs and leaves the
failing step completed."""
import contextlib
import io
import json
import re
import sys
import textwrap
import pathlib
import unittest

CI = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def _extract_guard() -> str:
    txt = CI.read_text(encoding="utf-8")
    m = re.search(r"<<'PY'\n(.*?)\n\s*PY\n", txt, re.S)
    assert m, "runner-restore heredoc not found in ci.yml"
    return textwrap.dedent(m.group(1))


def _run_guard(jobs_payload, log_map):
    """Exec the inline guard with a fake `gh`; returns (rc, stdout, rerun_ids)."""
    ns = {"__name__": "runner_restore_guard_under_test"}
    exec(compile(_extract_guard(), "guard.py", "exec"), ns)
    rerun_ids = []

    def fake_gh(*args):
        if "rerun" in args[-1]:
            rerun_ids.append(args[-1].rstrip("/").split("/")[-2])
            return ""
        url = args[1]
        if url.endswith("/logs"):
            jid = url.rstrip("/").split("/")[-2]
            if jid in log_map:
                return log_map[jid]
            raise RuntimeError("gh: HTTP 404 (BlobNotFound)")
        if "/attempts/" in url:
            return json.dumps(jobs_payload)
        raise RuntimeError("unexpected gh call: %r" % (args,))

    ns["gh"] = fake_gh
    class _T:
        sleep = staticmethod(lambda s: None)  # keep tests fast
    ns["time"] = _T
    sys.argv = ["guard.py", "--repo", "o/r", "--run-id", "1", "--run-attempt", "2"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ns["main"]()
    return rc, buf.getvalue(), rerun_ids


def _job(jid, step_status="in_progress", step_conclusion=None):
    steps = [
        {"name": "install test deps", "status": "completed", "conclusion": "success"},
        {"name": "run python tests", "status": step_status, "conclusion": step_conclusion},
    ]
    return {"id": jid, "name": "test", "conclusion": "failure", "steps": steps}


class TestRunnerRestoreNoLogRerun(unittest.TestCase):
    def test_transport_failure_without_log_blob_is_rerun(self):
        """RED on old guard: log 404 + frozen step -> guard must rerun the job."""
        payload = {"jobs": [_job(555)]}
        rc, out, reran = _run_guard(payload, log_map={})
        self.assertEqual(rc, 0)
        self.assertIn("555", reran, "guard skipped a transport-failed job with no log blob")

    def test_real_failure_with_completed_steps_is_not_rerun(self):
        payload = {"jobs": [_job(556, step_status="completed", step_conclusion="failure")]}
        rc, out, reran = _run_guard(payload, log_map={})
        self.assertEqual(reran, [], "real verdict must not be rerun")

    def test_log_with_transport_signature_is_still_rerun(self):
        log = "System.AggregateException: An error occurred while sending the request."
        payload = {"jobs": [_job(557, step_status="completed", step_conclusion="failure")]}
        rc, out, reran = _run_guard(payload, log_map={"557": log})
        self.assertIn("557", reran, "classic signature via log must keep rerunning")

    def test_log_without_signature_is_not_rerun(self):
        payload = {"jobs": [_job(558, step_status="completed", step_conclusion="failure")]}
        rc, out, reran = _run_guard(payload, log_map={"558": "normal failure output"})
        self.assertEqual(reran, [])


if __name__ == "__main__":
    unittest.main()
