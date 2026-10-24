"""25.10: docker-janitor на ПК пересоздаёт ace-step своим recreate'ом БЕЗ UV_NO_SYNC и выигрывает
гонку у workflow'а (создал 18:57, workflow'у достался 'name already in use') -> venv снова
пересинхронизировался и health висел в starting. Класс: любое recreate-место ace-step обязано
ставить UV_NO_SYNC=1, включая host-side janitor.sh. Закрытие: workflow janitor-sync синхронизирует
host-файл из эталона в репо (deploy/gpu-pc/janitor.sh) и перезапускает docker-janitor."""
import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
WF = ".github/workflows/janitor-sync.yml"
REF = "deploy/gpu-pc/janitor.sh"

def test_reference_janitor_sets_uv_no_sync():
    s = (ROOT / REF).read_text()
    assert s.count("UV_NO_SYNC=1") >= s.count("docker run -d --name ace-step"), "recreate без UV_NO_SYNC"

def test_sync_workflow_targets_janitor():
    s = (ROOT / WF).read_text()
    assert "hermes-ops/janitor" in s, "workflow должен писать host-файл janitor.sh"
    assert REF in s, "workflow должен брать эталон из репо"
    assert "docker-janitor" in s and "restart" in s, "после патча janitor обязан перезапуститься"

if __name__ == "__main__":
    test_reference_janitor_sets_uv_no_sync(); test_sync_workflow_targets_janitor(); print("ok")
