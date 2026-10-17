#!/usr/bin/env python3
"""Анти-повтор (спец t_b4006a6e п.3, карточка t_e39908b1): chroma-схожесть нового трека с треками,
опубликованными за 14 дней, выше порога = FAIL и регенерация. Одинаковые треки FAIL, разные PASS."""
import datetime as dt, json, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import antirepeat as ar

D = dt.date(2026, 10, 17)


def tone(path, chords, extra=""):
    """Аккордовая последовательность синусами (по 4 с на аккорд), stereo mp3."""
    parts = []
    for i, ch in enumerate(chords):
        parts.append("+".join(f"sin(2*PI*{f}*t)" for f in ch) + f"*between(mod(t,{4 * len(chords)}),{4 * i},{4 * i + 4})")
    expr = "0.2*(" + "+".join(parts) + ")"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=22050:d=150",
                    "-ac", "2", *extra.split(), str(path)], check=True)


C, F, G, Am, Dm, E = [261.6, 329.6, 392.0], [349.2, 440.0, 523.3], [392.0, 493.9, 587.3], [220.0, 261.6, 329.6], \
    [293.7, 349.2, 440.0], [329.6, 415.3, 493.9]
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    a, b = td / "a.mp3", td / "b.mp3"
    tone(a, [C, G, Am, F])
    tone(b, [Dm, E, Am, G, F, C])
    # «тот же трек» глазами гейта: перекодирован, тише на 3 дБ, сдвинут на 5 с
    a2 = td / "a2.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "5", "-i", str(a), "-af", "volume=-3dB",
                    "-b:a", "128k", str(a2)], check=True)
    fa, fa2, fb = ar.fingerprint(a), ar.fingerprint(a2), ar.fingerprint(b)
    s_same, s_diff = ar.similarity(fa2, fa), ar.similarity(fb, fa)
    print(f"same {s_same:.3f} diff {s_diff:.3f} threshold {ar.THRESHOLD}")
    assert s_same > ar.THRESHOLD > s_diff, (s_same, s_diff)
    # хранение: base64 int8 не ломает сравнение
    assert ar.similarity(fa2, ar.decode(ar.encode(fa))) > ar.THRESHOLD

    # окно 14 дней: запись 3 дня назад ловится, 15 дней назад не учитывается
    state = td / "antirepeat.json"
    ar.record(state, fa, D - dt.timedelta(days=3), video="vidA", genre="anime lofi")
    assert ar.check(fa2, ar.load(state), D), "одинаковый трек за 14 дней должен дать FAIL"
    assert not ar.check(fb, ar.load(state), D), "разный трек должен дать PASS"
    assert not ar.check(fa2, ar.load(state), D + dt.timedelta(days=12)), "запись старше 14 дней не учитывается"
    # record чистит записи старше 14 дней (state не растёт бесконечно)
    ar.record(state, fb, D + dt.timedelta(days=12), video="vidB", genre="chill phonk")
    assert [e["video"] for e in ar.load(state)] == ["vidB"], ar.load(state)

    # гейт: FAIL -> регенерация, повтор после регенерации -> FAIL (не публикуем), новый трек -> PASS
    entries = [{"date": str(D - dt.timedelta(days=1)), "video": "vidA", "genre": "x", "fp": ar.encode(fa)}]
    queue = [a2, b]
    calls = []

    def regen():
        calls.append(1)
        return queue.pop(0)

    assert ar.gate(lambda: a2, entries, D, regen, retries=1, log=lambda *x: None) is False
    assert calls == [1], "FAIL обязан запустить регенерацию"
    queue[:] = [b]
    assert ar.gate(lambda: a2, entries, D, regen, retries=1, log=lambda *x: None) is True
    assert ar.gate(lambda: b, entries, D, lambda: 1 / 0, retries=1, log=lambda *x: None) is True  # PASS без регенерации
    # регенерация не прошла quality_gate (regen -> None) -> FAIL
    assert ar.gate(lambda: a2, entries, D, lambda: None, retries=1, log=lambda *x: None) is False

# workflow: шаг гейта сразу после 03c, отпечатки коммитятся force-add
wf = (Path(__file__).parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
names = [l.split("name:", 1)[1].strip() for l in wf.splitlines() if l.strip().startswith("- name:")]
i = next(k for k, n in enumerate(names) if n.startswith("03c"))
assert names[i + 1].startswith("03d") and "antirepeat" in wf.split(names[i + 1], 1)[1].split("- name:", 1)[0], names
assert "git add -f .state/antirepeat.json" in wf
assert "antirepeat.py --record" in wf
assert ar.WINDOW_DAYS == 14
print("test_antirepeat OK")
