"""24.10: entrypoint ace-step делает `uv run`, тот пересинхронизировал venv (качал torch ~10 МБ/мин),
контейнер 40+ мин висел в health=starting -> выпуск упал на шаге ACE-Step up. Каждое пересоздание обязано ставить UV_NO_SYNC=1."""
import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = [".github/workflows/daily-video.yml", ".github/workflows/xl-probe.yml", "deploy/gpu-pc/ensure_ace_step.sh"]

def test_recreate_sets_uv_no_sync():
    for f in FILES:
        s = (ROOT / f).read_text()
        runs = s.count("--name ace-step")
        assert runs, f
        assert s.count("UV_NO_SYNC=1") >= runs, f

if __name__ == "__main__":
    test_recreate_sets_uv_no_sync(); print("ok")
