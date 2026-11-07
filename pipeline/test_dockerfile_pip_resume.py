"""t_a929cfc3: every Dockerfile that pip-installs torch must first pin pip>=26.2 (Range resume).

jammy python3-venv ships pip 22.0.2: one dropped connection on the ~800 MB torch wheel kills the layer
(build-ace-step-image runs 39927449738..39928382766: "TimeoutError: The read operation timed out").
"""
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PIP = re.compile(r'"?pip==(\d+)\.(\d+)')
TORCH = re.compile(r"pip install[^\n]*\btorch\b")


def check(text):
    t = TORCH.search(text)
    if not t:
        return None
    m = PIP.search(text)
    if not m or m.start() > t.start():
        return "pip==X.Y must be installed before torch (jammy pip 22 cannot resume downloads)"
    if (int(m[1]), int(m[2])) < (26, 2):
        return f"pip {m[1]}.{m[2]} < 26.2: no safe Range resume"
    if "PIP_RESUME_RETRIES" not in text:
        return "PIP_RESUME_RETRIES must be set"
    return None


def test_all_dockerfiles():
    bad = {}
    for p in ROOT.rglob("Dockerfile*"):
        if ".git" in p.parts or "node_modules" in p.parts:
            continue
        err = check(p.read_text(errors="ignore"))
        if err:
            bad[str(p.relative_to(ROOT))] = err
    assert not bad, bad


def test_check_catches_old_pattern():
    old = 'RUN python -m venv /opt/venv\nRUN pip install --no-cache-dir torch torchvision torchaudio\n'
    assert check(old)
    assert check('RUN pip install "pip==22.0.2"\nENV PIP_RESUME_RETRIES=20\nRUN pip install torch\n')
    assert check('RUN pip install "pip==26.2.2"\nRUN pip install torch\n') == "PIP_RESUME_RETRIES must be set"
    assert check('RUN pip install "pip==26.2.2"\nENV PIP_RESUME_RETRIES=20\nRUN pip install torch\n') is None


if __name__ == "__main__":
    test_check_catches_old_pattern(); test_all_dockerfiles(); print("ok")
