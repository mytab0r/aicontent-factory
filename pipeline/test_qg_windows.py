#!/usr/bin/env python3
"""Spec tests for the audio quality-gate window/CE API.

Written ONLY against the API spec: pipeline/quality_gate.py and
pipeline/03_music.py are implemented in parallel and must not be read here.
Plain script, no pytest:

    python3 pipeline/test_qg_windows.py      # from repo root

Stdlib + ffmpeg/ffprobe CLI + tempfile only.  Prints 'test_qg_windows OK' at end.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import quality_gate as qg  # noqa: E402

_spec = importlib.util.spec_from_file_location('music_x', Path(__file__).parent / '03_music.py')
music = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(music)


# ---------------------------------------------------------------- ffmpeg helpers

def run(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    *(str(a) for a in args)], check=True)


def dur_of(path):
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                   '-of', 'default=noprint_wrappers=1:nokey=1', str(path)])
    return float(out.strip())


def synth(d, name, parts):
    """Stereo 48 kHz s16le wav built from ('sine'|'noise', seconds) parts, concatenated."""
    pieces = []
    for i, (kind, dur) in enumerate(parts):
        p = Path(d) / f'{name}__{i}.wav'
        src = ('sine=frequency=220:sample_rate=48000:duration=%s' % dur if kind == 'sine' else
               'anoisesrc=colour=white:amplitude=0.7:sample_rate=48000:duration=%s' % dur)
        run('-f', 'lavfi', '-i', src, '-ac', '2', '-c:a', 'pcm_s16le', p)
        pieces.append(p)
    out = Path(d) / f'{name}.wav'
    if len(pieces) == 1:
        pieces[0].replace(out)
        return out
    args = []
    for p in pieces:
        args += ['-i', str(p)]
    fc = ''.join(f'[{k}:a]' for k in range(len(pieces))) + f'concat=n={len(pieces)}:v=0:a=1'
    run(*args, '-filter_complex', fc, '-c:a', 'pcm_s16le', out)
    return out


# ---------------------------------------------------------------- fake critic

_NEG = bytes(48 if b < 128 else 49 for b in range(256))  # int16 LE: hi byte >= 128 -> negative -> b'1'


def zcr_critic(good, bad, noisy_zcr=3000.0, block=0.5):
    """Deterministic fake critic.  Fraction of 0.5 s blocks whose zero-crossing
    rate exceeds noisy_zcr/s (220 Hz sine ~440/s, white noise >15000/s) maps to
    CE = good - frac * (good - bad).  Accepts any 16-bit PCM wav rate;
    stereo is reduced to channel 0."""
    def fake(paths):
        scores = []
        for p in paths:
            with wave.open(str(p), 'rb') as w:
                nch, sw, rate, nf = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
                raw = w.readframes(nf)
            if sw != 2:
                raise RuntimeError(f'expected 16-bit wav clip, got sampwidth={sw}: {p}')
            step, blk = 2 * nch, max(1, int(rate * block))
            noisy = total = 0
            for off in range(0, nf, blk):
                n = min(blk, nf - off)
                if n <= 0:
                    continue
                t = raw[1 + off * step: 1 + (off + n) * step: step].translate(_NEG)
                total += 1
                if (t.count(b'01') + t.count(b'10')) / (n / rate) > noisy_zcr:
                    noisy += 1
            frac = noisy / total if total else 1.0
            scores.append(good - frac * (good - bad))
        return scores
    return fake


def run_main(args, cwd):
    """qg.main() with cwd parked in the temp dir (main may drop side files)."""
    prev = os.getcwd()
    os.chdir(cwd)
    try:
        return qg.main([str(a) for a in args])
    finally:
        os.chdir(prev)


# ---------------------------------------------------------------- spec tests

def test_constants_and_windows():
    assert qg.MIN_CE == 6.5
    assert qg.WIN == 30.0
    assert qg.DRIFT_HEAD == 60.0
    assert qg.DRIFT_MAX == 0.5
    assert qg.SEAM_HALF == 5.0
    assert qg.SEAM_RMS_MAX == 3.0
    assert qg.windows(100) == [(0, 30), (30, 30), (60, 30), (70, 30)]
    assert qg.windows(90) == [(0, 30), (30, 30), (60, 30)]
    assert qg.windows(20) == [(0.0, 20)]
    for dur in (0.5, 30.0, 30.1, 60.0, 60.1, 100.0, 180.0):
        ws = qg.windows(dur)
        assert ws and ws[0][0] == 0
        assert abs((ws[-1][0] + ws[-1][1]) - dur) < 1e-9   # union covers [0, dur]
        for (s1, l1), (s2, _l2) in zip(ws, ws[1:]):
            # base windows are consecutive; the final end-aligned one may overlap
            assert l1 > 0 and s2 > s1


def test_ce_why_boundaries():
    assert qg.ce_why([])                    # critic produced nothing -> FAIL
    assert qg.ce_why([(0, 7.5), (30, 7.4), (60, 7.3), (90, 7.5)]) == []   # flat good
    assert any('R1' in r for r in qg.ce_why([(0, 7.5), (30, 6.49)]))
    assert qg.ce_why([(0, 7.5), (30, 7.5), (60, 7.0), (90, 7.0)]) == []   # drift == 0.5 passes
    assert any('R2' in r for r in qg.ce_why([(0, 7.51), (30, 7.51), (60, 7.0), (90, 7.0)]))


def test_seam_why_boundaries():
    assert qg.seam_why([]) == []
    assert qg.seam_why([{'t': 12.5, 'ce': 7.0, 'rms_l': -6.0, 'rms_r': -6.0}]) == []
    # rms gap exactly 3.0 passes
    assert qg.seam_why([{'t': 12.5, 'ce': 7.0, 'rms_l': -6.0, 'rms_r': -9.0}]) == []
    assert any('R3' in r for r in qg.seam_why([{'t': 12.5, 'ce': 7.0, 'rms_l': -6.0, 'rms_r': -9.01}]))
    assert any('R3' in r for r in qg.seam_why([{'t': 12.5, 'ce': 6.4, 'rms_l': -6.0, 'rms_r': -6.0}]))


def test_music_helpers():
    assert music.XFADE == 16.0  # t_ffa7ff01: шире кроссфейд — плавнее RMS-переход R3
    assert music.seam_times([100, 100, 100]) == [92.0, 176.0]
    assert music.chapters([100, 100], ['A', 'B'], xfade=8) == ['0:00 A', '1:32 B']
    assert music.chapters([482.0, 482.0], ['A', 'B'])[1] == '8:02 B'


def test_case_a(f, d):
    # complaint 18.10: first seconds great, then mush (mush still above MIN_CE)
    fake = zcr_critic(good=7.6, bad=6.8)
    old = qg.ce_batch([str(f)], critic=fake)[0]        # legacy gate: 3 clips @ 10/50/90 %
    assert len(old) == 3 and min(old) >= qg.MIN_CE     # OLD gate PASSES
    why, rep = qg.full_ce_why(str(f), critic=fake)     # NEW gate must FAIL
    assert why and any('R2' in r for r in why)
    assert [s for s, _ce in rep['wins']] == [s for s, _l in qg.windows(dur_of(f))]


def test_case_b(f):
    # local dip 110..140 s falls between the legacy sample points
    fake = zcr_critic(good=7.6, bad=4.0)
    old = qg.ce_batch([str(f)], critic=fake)[0]        # clips [3,33] [75,105] [147,177]
    assert min(old) >= qg.MIN_CE                       # OLD gate PASSES
    why, _rep = qg.full_ce_why(str(f), critic=fake)    # NEW gate must FAIL
    assert why and any('R1' in r for r in why)


def test_good(f):
    why, rep = qg.full_ce_why(str(f), critic=zcr_critic(good=7.6, bad=4.0))
    assert why == []
    assert len(rep['wins']) == len(qg.windows(dur_of(f)))


def test_seams(d):
    d = Path(d)
    loud = d / 'seam_loud.wav'
    run('-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=48000:duration=60',
        '-ac', '2', '-c:a', 'pcm_s16le', loud)
    quiet = d / 'seam_quiet.wav'
    run('-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=48000:duration=60',
        '-af', 'volume=-12dB', '-ac', '2', '-c:a', 'pcm_s16le', quiet)
    joined = d / 'seam_joined.wav'
    music.concat_tracks([str(loud), str(quiet)], str(joined))
    assert abs(dur_of(joined) - (60 + 60 - music.XFADE)) <= 0.3
    ts = music.seam_times([60.0, 60.0])
    assert len(ts) == 1 and abs(ts[0] - 56.0) < 1e-9
    fake = zcr_critic(good=7.6, bad=4.0)
    why, rep = qg.full_ce_why(str(joined), seams=ts, critic=fake)
    assert len(rep['seams']) == 1 and abs(rep['seams'][0]['t'] - 56.0) < 1e-9
    assert abs(rep['seams'][0]['rms_l'] - rep['seams'][0]['rms_r']) > qg.SEAM_RMS_MAX
    assert any('R3' in r for r in why)
    same = d / 'seam_same.wav'
    music.concat_tracks([str(loud), str(loud)], str(same))
    why2, rep2 = qg.full_ce_why(str(same), seams=ts, critic=fake)
    assert len(rep2['seams']) == 1
    assert abs(rep2['seams'][0]['rms_l'] - rep2['seams'][0]['rms_r']) <= qg.SEAM_RMS_MAX
    assert not any('R3' in r for r in why2)


def test_r5_critic_failure(f, d):
    def boom(_paths):
        raise RuntimeError('critic down')
    why, _rep = qg.full_ce_why(str(f), critic=boom)    # must NOT raise
    assert why and any('R5' in r for r in why)

    def wrong_count(paths):
        return [7.0] * max(len(paths) - 1, 0)
    why2, _rep2 = qg.full_ce_why(str(f), critic=wrong_count)
    assert why2
    orig = qg.critic_clips
    qg.critic_clips = boom
    try:
        assert run_main(['x', str(f), 'anime lofi'], cwd=d) == 1
    finally:
        qg.critic_clips = orig


def test_final_mp4(d, case_a):
    d = Path(d)
    mp4 = d / 'final.mp4'
    run('-f', 'lavfi', '-i', 'color=gray:size=64x64:rate=5', '-i', str(case_a), '-shortest',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', mp4)
    fake = zcr_critic(good=7.6, bad=6.8)
    orig = qg.critic_clips
    qg.critic_clips = fake
    try:
        assert run_main(['x', str(mp4), 'anime lofi', '--final'], cwd=d) == 1
    finally:
        qg.critic_clips = orig
    why, _rep = qg.full_ce_why(str(mp4), critic=fake)
    assert any('R2' in r for r in why)


def main():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        case_a = synth(d, 'case_a', [('sine', 60), ('noise', 120)])
        case_b = synth(d, 'case_b', [('sine', 110), ('noise', 30), ('sine', 40)])
        good = synth(d, 'good', [('sine', 180)])
        test_constants_and_windows()
        test_ce_why_boundaries()
        test_seam_why_boundaries()
        test_music_helpers()
        test_case_a(case_a, d)
        test_case_b(case_b)
        test_good(good)
        test_seams(d)
        test_r5_critic_failure(case_a, d)
        test_final_mp4(d, case_a)
    print('test_qg_windows OK')


if __name__ == '__main__':
    main()
