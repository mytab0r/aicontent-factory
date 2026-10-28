#!/usr/bin/env python3
"""t_3c5e7da4: каждый `docker run` образа раннера в workflows обязан задавать HostConfig.Dns с фолбэком
и кеш action-архивов — тот же список, что pxbt-infra scripts/runner_dns.py (DNS/CACHE_*).
Дрейф 23-25.10: runner-unbreak/pc-ops пересоздавали gh-runner-aicontent-factory/acf-release без --dns ->
runner-dns check красный (Dns != [...]) + сбои резолва github.com. Запуск: python3 pipeline/test_runner_dns_config.py"""
import re
from pathlib import Path

WF = Path(__file__).resolve().parent.parent / ".github/workflows"
DNS = ["192.168.65.7", "8.8.8.8", "77.88.8.8"]  # = pxbt-infra runner_dns.DNS; менять только вместе
CACHE = ["-e ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE=/opt/actions-archive-cache",
         "-v gh-actions-archive-cache:/opt/actions-archive-cache"]
IMAGE = "myoung34/github-runner"


def runner_runs(text):
    """-> склеенные (по `\\`) команды `docker run`, запускающие образ раннера."""
    cmds = re.findall(r"docker run\b(?:[^\n]*\\\n)*[^\n]*", text)
    return [re.sub(r"\\\n\s*", " ", c) for c in cmds if IMAGE in c or '"$tag"' in c]  # $tag: janitor swap_runner


def problems(cmd):
    bad = []
    if re.findall(r"--dns[ =](\S+)", cmd) != DNS:
        bad.append(f"--dns != {DNS}")
    bad += [f"нет {c}" for c in CACHE if c not in cmd]
    return bad


def test_selfcheck():
    ok = ("docker run -d --dns 192.168.65.7 --dns 8.8.8.8 --dns 77.88.8.8 \\\n  " + " ".join(CACHE) +
          " \\\n  myoung34/github-runner:ubuntu-noble\n")
    assert [problems(c) for c in runner_runs(ok)] == [[]]
    drift = "docker run -d --name x --cpus 4 \\\n  -e A=1 \\\n  myoung34/github-runner:ubuntu-noble\ndocker run alpine\n"
    (c,) = runner_runs(drift)
    assert problems(c)[0].startswith("--dns"), problems(c)


def test_workflows():
    seen, bad = 0, []
    for f in sorted(WF.glob("*.yml")) + [WF.parent.parent / "deploy/gpu-pc/janitor.sh"]:
        for c in runner_runs(f.read_text(encoding="utf-8")):
            seen += 1
            bad += [f"{f.name}: {p}" for p in problems(c)]
    assert seen >= 3, f"найдено {seen} docker run раннера — парсер сломан?"
    assert not bad, "раннер создаётся без DNS-фолбэка/кеша (дрейф HostConfig.Dns, t_3c5e7da4):\n" + "\n".join(bad)


def test_docker_top_has_pid():
    """docker top без колонки pid -> ошибка API -> проверка «раннер занят» молча врёт (t_5cdbb967, 27.10)."""
    src = (WF.parent.parent / "deploy/gpu-pc/janitor.sh").read_text(encoding="utf-8")
    tops = re.findall(r"docker top \S+ -eo (\S+)", src)
    assert tops and all("pid" in t.split(",") for t in tops), tops


if __name__ == "__main__":
    test_selfcheck()
    test_workflows()
    test_docker_top_has_pid()
    print("OK test_runner_dns_config")
