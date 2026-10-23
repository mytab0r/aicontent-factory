#!/usr/bin/env python3
"""t_b1429246: self-hosted runner transport failure = job fails with
System.AggregateException "(An error occurred while sending the request.)" —
Runner.Worker could not deliver CompleteJobAsync to GitHub (HttpIOException:
"The response ended prematurely") during PC-egress degradation windows.
All steps already ran; GitHub has no verdict. Detect that signature on this
run's failed jobs and re-run each affected job so the verdict is real.
Stdlib-only; never raises (guard job must not fail the run)."""
import argparse
import json
import re
import subprocess
import sys
import time

SIG = re.compile(r"System\.AggregateException[\s\S]{0,400}?An error occurred while sending the request")


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--run-id", type=int, required=True)
    ap.add_argument("--run-attempt", type=int, required=True)
    a = ap.parse_args()
    try:
        jobs = json.loads(gh("api", f"repos/{a.repo}/actions/runs/{a.run_id}/attempts/{a.run_attempt}/jobs"))["jobs"]
    except Exception as e:
        print(f"::warning::jobs list unavailable, skip restore: {e}")
        return 0
    reran = 0
    for j in jobs:
        if j.get("conclusion") != "failure":
            continue
        try:
            log = gh("api", f"repos/{a.repo}/actions/jobs/{j['id']}/logs")
        except Exception:
            continue  # log expired/unavailable -> can't confirm signature, treat as real verdict
        if not SIG.search(log):
            continue
        print(f"runner transport failure: job {j['name']} ({j['id']}) -> rerun")
        time.sleep(15)  # let the worker release the job before the rerun lands
        try:
            gh("api", "-X", "POST", f"repos/{a.repo}/actions/jobs/{j['id']}/rerun")
            reran += 1
        except Exception as e:
            print(f"::warning::rerun of job {j['id']} failed: {e}")
    print(f"restored {reran} job(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
