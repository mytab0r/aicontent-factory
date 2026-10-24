"""A26: речевые ролики (whatif/owning) мастерятся с запасом true peak.
Замер 24.10 копий YouTube канала 2: THKn6SVp6g8 TP -0.87 dBTP при мастере loudnorm TP=-1.5
(Opus-перекод добавляет ~0.6 дБ) — выше гейта MAX_TP -1.0. Нужен TP <= -2.0 в loudnorm речи."""
import pathlib, re

SRC = ["pipeline/whatif_channel.py", "pipeline/owning_channel.py"]
ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_speech_loudnorm_tp_headroom():
    for s in SRC:
        txt = (ROOT / s).read_text()
        tps = [float(x) for x in re.findall(r"loudnorm=[^\"]*?TP=(-?[0-9.]+)", txt)]
        assert tps, s
        assert all(tp <= -2.0 for tp in tps), (s, tps)
