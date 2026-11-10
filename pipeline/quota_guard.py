"""Quota guard for ZeroGPU / HF Spaces.

Tracks quota exhaustion state with 24h TTL. Fails fast before hitting HF limits.
Zero external dependencies — uses local file state.
"""
import os
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("QUOTA_GUARD_STATE_DIR", ".state"))
EXHAUSTED_FILE = STATE_DIR / "zerogpu_exhausted"
QUOTA_WINDOW_SEC = 24 * 3600  # 24 hours


def is_exhausted() -> bool:
    """Return True if quota was marked exhausted within the last 24h."""
    try:
        if not EXHAUSTED_FILE.exists():
            return False
        mtime = EXHAUSTED_FILE.stat().st_mtime
        return (time.time() - mtime) < QUOTA_WINDOW_SEC
    except Exception:
        return False


def mark_exhausted(reason: str) -> None:
    """Mark quota as exhausted with reason (written to file for debugging)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EXHAUSTED_FILE.write_text(f"{reason}\n{time.time()}\n", encoding="utf-8")


def reset() -> None:
    """Force reset quota state (for testing or manual recovery)."""
    EXHAUSTED_FILE.unlink(missing_ok=True)
