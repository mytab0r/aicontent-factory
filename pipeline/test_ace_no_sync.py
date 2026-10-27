"""24.10: entrypoint ace-step делает `uv run`, тот пересинхронизировал venv (качал torch ~10 МБ/мин),
контейнер 40+ мин висел в health=starting -> выпуск упал на шаге ACE-Step up. Каждое пересоздание обязано ставить UV_NO_SYNC=1."""
import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
# t_f3937fb8: список не хардкодим — recreate переехал в ace_mode.sh, тест ловит любое новое место пересоздания.
FILES = [str(p.relative_to(ROOT)) for d in (".github/workflows", "deploy") for p in sorted((ROOT / d).rglob("*"))
         if p.suffix in (".yml", ".yaml", ".sh") and "docker run" in p.read_text(errors="ignore") and "--name ace-step" in p.read_text(errors="ignore")]

def test_recreate_sets_uv_no_sync():
    assert {"deploy/gpu-pc/ace_mode.sh", "deploy/gpu-pc/ensure_ace_step.sh"} <= set(FILES), FILES
    for f in FILES:
        s = (ROOT / f).read_text()
        runs = s.count("--name ace-step")
        assert runs, f
        assert s.count("UV_NO_SYNC=1") >= runs, f

if __name__ == "__main__":
    test_recreate_sets_uv_no_sync(); print("ok")
