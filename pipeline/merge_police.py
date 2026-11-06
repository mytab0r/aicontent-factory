"""P10 (аудит 25.10): детектор преждевременного мержа — merge раньше зелёного `test`.

GitHub Free на private-репо: branch protection и rulesets недоступны (API 403
"Upgrade to GitHub Pro"). Обходного механизма принуждения нет, поэтому класс
(PR #88, PR #205 — merged при pending-проверках) ловит этот детектор: CI на
push в master находит PR HEAD-коммита (squash) и проверяет, что required-чек
`test` его HEAD-ветки завершился success ДО merge (допуск SLACK_S на лаг
между зелёным чеком и авто-мержем). Нарушение = ::error + красный job + TG-алерт.

Запуск в Actions: GITHUB_REPOSITORY, GITHUB_SHA, GH_TOKEN (github.token).
Коды выхода: 0 = ок / нет PR (direct push), 1 = преждевременный merge или
ошибка проверки (fail-closed).
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta

CHECK = "test"   # required check = job test в ci.yml (authoritative gate репо)
SLACK_S = 120    # допуск между завершением test и merge (poll/auto-merge)


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def evaluate(merged_at: str, check_completed_at, check_conclusion, slack_s: int = SLACK_S) -> dict:
    """Вердикт: green-ли чек `CHECK` ДО merge (+slack)."""
    if check_conclusion != "success":
        return {"premature": True, "why": f"check '{CHECK}' conclusion={check_conclusion!r} — не success"}
    if not check_completed_at:
        return {"premature": True, "why": f"check '{CHECK}' без completed_at"}
    if parse_ts(check_completed_at) > parse_ts(merged_at) + timedelta(seconds=slack_s):
        return {"premature": True,
                "why": f"check '{CHECK}' завершился {check_completed_at} ПОЗЖЕ merge {merged_at} (+{slack_s}s допуск)"}
    return {"premature": False, "why": f"check '{CHECK}' success {check_completed_at}, merge {merged_at}"}


def decide(pr: dict, check_runs: list) -> dict:
    """Вердикт по PR + его check-runs (HEAD-ветка). Нет чека `CHECK` = premature."""
    ours = [c for c in check_runs if c.get("name") == CHECK]
    if not ours:
        return {"premature": True,
                "why": f"чек '{CHECK}' на HEAD {pr.get('head', {}).get('sha', '?')[:12]} не найден — merge без прогона test"}
    c = ours[0]
    return evaluate(pr["merged_at"], c.get("completed_at"), c.get("conclusion"))


def _api(url: str, token: str):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "merge-police",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY")
    sha = os.environ.get("GITHUB_SHA")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not repo or not sha or not token:
        print("merge-police: вне Actions (нет GITHUB_REPOSITORY/GITHUB_SHA/GH_TOKEN) — пропуск", file=sys.stderr)
        return 0
    try:
        prs = _api(f"https://api.github.com/repos/{repo}/commits/{sha}/pulls", token)
        merged = [p for p in prs if p.get("merged_at")]
        if not merged:
            print(json.dumps({"premature": False, "why": "push без PR (direct push) или PR не найден"}, ensure_ascii=False))
            return 0
        pr = merged[0]
        head = pr["head"]["sha"]
        data = _api(f"https://api.github.com/repos/{repo}/commits/{head}/check-runs?per_page=100", token)
        verdict = decide({"number": pr["number"], "merged_at": pr["merged_at"], "head": {"sha": head}},
                         data.get("check_runs", []))
    except Exception as e:  # fail-closed: не смогли проверить = тревога
        print(f"::error::merge-police не смог проверить HEAD ({e})")
        return 1
    verdict.update({"pr": pr["number"], "merged_at": pr["merged_at"]})
    print(json.dumps(verdict, ensure_ascii=False))
    if verdict["premature"]:
        print(f"::error::P10 преждевременный merge PR #{pr['number']}: {verdict['why']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
