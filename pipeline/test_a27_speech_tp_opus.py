#!/usr/bin/env python3
"""A27: true peak речевого мастера с запасом на Opus YouTube. Регрессия на цифрах 26.10:
YouTube-копии K5cqI_AX4hk -0.3 и kQauDNrBAWU -0.8 dBTP; мастер около -1.1 проходил старый гейт (MAX_TP -1.0)."""
import pathlib, shutil, subprocess, sys, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import quality_gate as qg


def _mk(out, gain_db):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"anoisesrc=d=6:c=pink:a=0.3,loudnorm=I=-14:TP={gain_db}", "-ar", "48000", "-c:a", "aac", "-b:a", "160k", str(out)],
                   check=True)
    return out


def _tp(f):
    import re
    return float(re.findall(r"Peak:\s+(-?[\d.]+)", qg.ff(f, "ebur128=peak=true"))[-1])


def test_speech_tp_margin_constant():
    assert qg.SPEECH_TP_MAX <= -1.6, qg.SPEECH_TP_MAX  # не ослаблять


def test_speech_master_without_headroom_fails():
    if not shutil.which("ffmpeg"):
        print("skip: нет ffmpeg")
        return
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        thin = _mk(d / "thin.m4a", -1.1)   # как мастер до A26: проходил MAX_TP -1.0, на YouTube -0.3..-0.8
        ok = _mk(d / "ok.m4a", -2.0)       # мастер A26
        assert -1.6 < _tp(thin) <= qg.MAX_TP, _tp(thin)  # фикстура: старый гейт её пропускал
        assert any("true peak" in w for w in qg.speech_why(thin)), qg.speech_why(thin)
        assert not any("true peak" in w for w in qg.speech_why(ok)), (_tp(ok), qg.speech_why(ok))


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
