"""daily-video обязан рестартовать ace-step перед 03 music: зависшая задача от xl-probe валила выпуск (17.10)."""
import pathlib
WF = (pathlib.Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text()

def test_ace_restart_before_music():
    up = WF.index("name: ACE-Step up")
    music = WF.index("name: 03 music")
    assert "docker restart ace-step" in WF[up:music]

if __name__ == "__main__":
    test_ace_restart_before_music(); print("ok")
