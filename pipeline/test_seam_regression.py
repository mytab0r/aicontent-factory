#!/usr/bin/env python3
"""Regression test for t_2be41a12: seam RMS spike on segment joins.

Root cause: _downbeats() caught ImportError and returned None when librosa was
missing, so dj_plan() silently fell back to a plain xfade (no beat-grid cut,
no bass swap). On a segment edge with a transient (hit/breakdown) that xfade
leaves a seam RMS gap > SEAM_RMS_MAX that edge_match's gain-ramp correction
cannot fully close (two-sided gain correction was tried and still failed, see
t_2be41a12 history). Fix: librosa is now a hard pyproject dependency and
_downbeats no longer catches ImportError -- a missing librosa fails the run
loudly instead of silently degrading seam quality.

Run with: python3 pipeline/test_seam_regression.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_mix as T  # noqa: E402

music = T.music


def test_downbeats_propagates_missing_librosa_instead_of_silent_none():
    """librosa absent must raise, not silently degrade dj_plan to xfade (t_2be41a12)."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name.split(".")[0] == "librosa":
            raise ImportError(name)
        return real_import(name, *a, **k)

    music._downbeats.cache_clear()
    builtins.__import__ = blocked
    try:
        try:
            music._downbeats(__file__, 0.0, 1.0)
        except ImportError:
            pass
        else:
            raise AssertionError("_downbeats must raise ImportError, not return None/silently fall back")
    finally:
        builtins.__import__ = real_import
        music._downbeats.cache_clear()


def test_seam_rms_within_gate_threshold_with_librosa():
    """Same scenario as the real gate (t_e0c297c7/t_2be41a12): with librosa available,
    the DJ-cut seam stays inside SEAM_RMS_MAX, not just the gain-ramp-only fallback."""
    T.test_edge_match_measures_crossfaded_seam_like_gate()


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
