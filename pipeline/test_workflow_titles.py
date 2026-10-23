"""P21 (аудит 23.10): titles.json получил 6 заголовков за 23.10 при 0 public — пропущенный слот (nobank)
коммитил заголовок, сцена «сгорала» на 14 дней без выпуска. Заголовок коммитится только после успешной публикации."""
from pathlib import Path

WF = Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml"


def commit_step(text: str) -> str:
    return text.split("- name: commit mood rotation state", 1)[1].split("- name:", 1)[0]


def test_titles_committed_only_after_publish():
    step = commit_step(WF.read_text(encoding="utf-8"))
    line = next(l for l in step.splitlines() if "git add -f .state/titles.json" in l)
    assert 'PUB_OUTCOME="${{ steps.publish.outcome }}"' in step
    assert '"$PUB_OUTCOME" = "success"' in line, line


def test_unpublished_title_reverted_before_rebase():
    step = commit_step(WF.read_text(encoding="utf-8"))
    assert step.index("git checkout -- .state/titles.json") < step.index("git pull --rebase")
