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

def test_sync_pipes_file_not_workspace_bind():
    """run 40132476922: bind $GITHUB_WORKSPACE в docker run -> «can't stat /src/janitor.sh»: workspace
    раннера в его томе, демон хоста этот путь не видит. Файл обязан идти через stdin."""
    s = (ROOT / WF).read_text()
    assert '$GITHUB_WORKSPACE/deploy' not in s.split("docker restart")[0].replace("grep", ""), "bind workspace = пустой /src"
    assert "docker run --rm -i" in s and "< deploy/gpu-pc/janitor.sh" in s


def test_janitor_rotates_wsl_crash_dumps():
    """27.10: 10.7 ГБ дампов wsl-crashes в Windows Temp опустили C: под пол 30 ГБ -> bank-fill встал."""
    s = (ROOT / REF).read_text()
    assert "wsl-crashes" in s and "tail -n +2" in s, "janitor обязан ротировать дампы WSL (оставлять 1)"
    loop = s.split("while true; do", 1)[1]
    assert "purge_crashes" in loop, "purge_crashes не вызывается в цикле"
    assert "AppData/Local/Temp" in s and "-mtime +2" in s, "janitor обязан держать Windows Temp <= 2 суток"


def test_sync_verifies_rotation_landed():
    s = (ROOT / ".github/workflows/janitor-sync.yml").read_text()
    assert "grep -c purge_crashes /j/janitor.sh" in s, "sync обязан показать, что ротация доехала до host-копии"


if __name__ == "__main__":
    test_reference_janitor_sets_uv_no_sync(); test_sync_workflow_targets_janitor(); test_sync_pipes_file_not_workspace_bind(); test_janitor_rotates_wsl_crash_dumps(); test_sync_verifies_rotation_landed(); print("ok")
