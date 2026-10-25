import pathlib, re

WF = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/build-ace-step-image.yml"


def test_disk_gate_runs_before_any_pull_or_build():
    s = WF.read_text()
    gate = s.find("disk_gate.sh d ")
    assert gate != -1, "build-ace-step-image must call disk_gate.sh d before pulling/building"
    for step in ("docker pull", "buildx build"):
        assert gate < s.find(step), f"disk gate must precede {step}"


if __name__ == "__main__":
    test_disk_gate_runs_before_any_pull_or_build(); print("ok")
