"""t_a929cfc3: ACE-Step image must not install torch with jammy's pip 22 (no download resume).

Guard: venv pip pinned >= 26.2 before any torch install; torch triple + torchcodec pinned with ==.
"""
import pathlib, re

DF = pathlib.Path(__file__).resolve().parents[1] / "deploy/gpu-pc/Dockerfile"


def test_pip_upgraded_before_torch_and_pins():
    s = DF.read_text()
    m = re.search(r'"pip==(\d+)\.(\d+)(?:\.\d+)?"', s)
    assert m, "venv pip must be pinned (pip==X.Y) -- jammy pip 22 cannot resume downloads"
    assert (int(m[1]), int(m[2])) >= (26, 2), f"pip {m[1]}.{m[2]} < 26.2: no safe Range resume"
    torch = s.find("torch==")
    assert torch != -1 and m.start() < torch, "pip upgrade must precede torch install"
    assert "PIP_RESUME_RETRIES" in s, "PIP_RESUME_RETRIES must be set"
    for pkg in ("torch", "torchvision", "torchaudio", "torchcodec"):
        assert re.search(rf'"{pkg}==[\d.]+"', s), f"{pkg} must be pinned with =="


if __name__ == "__main__":
    test_pip_upgraded_before_torch_and_pins(); print("ok")
