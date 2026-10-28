"""t_5dec8455: auto-compact.ps1 fallback (Optimize-VHD -> diskpart) was silent: exit 0 on failure.
Invariant: failure is recorded, Docker restarted, then exit 1; script ASCII (PS 5.1 reads BOM-less as ANSI)."""
import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
PS = (ROOT / "deploy/gpu-pc/host/auto-compact.ps1").read_text()
WF = (ROOT / ".github/workflows/auto-compact-sync.yml").read_text()

def test_fallback_fails_loud():
    catch = PS.split("catch {", 1)[1].split("\n}", 1)[0]
    assert "$failed" in catch and "LASTEXITCODE" in catch, "catch must record failure + diskpart rc"
    tail = PS.rsplit("schtasks /run /tn DockerStart", 1)[1]
    assert "if ($failed)" in tail and "exit 1" in tail, "exit 1 must come after Docker restart"

def test_ascii_only():
    assert PS.isascii()

def test_sync_workflow_pipes_reference():
    assert "< deploy/gpu-pc/host/auto-compact.ps1" in WF and "docker run --rm -i" in WF

if __name__ == "__main__":
    test_fallback_fails_loud(); test_ascii_only(); test_sync_workflow_pipes_reference(); print("ok")
