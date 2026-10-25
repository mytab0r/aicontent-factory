#!/usr/bin/env python3
"""Release step that ONLY assembles from existing bank segments.
It expects bank to contain enough passed segments; if not, it exits with code 2
to signal slot skip (handled in workflow)."""
import os, sys, pathlib, json, random, subprocess, time
from pathlib import Path

# reuse functions from bank_release
import bank_release as br

run_dir = Path(os.getenv('ACF_RUN_DIR', Path.cwd()))
genre = os.getenv('GENRE')
if not genre:
    print('GENRE not set', file=sys.stderr); sys.exit(1)
# take from bank (no generation)
paths = br.take(genre, -1, str(run_dir), docker_sh=lambda *a: None, now=time.time, valid=lambda p: Path(p).stat().st_size>0)
if not paths:
    print('bank empty', file=sys.stderr); sys.exit(2)
metas = br.entries(genre, docker_sh=lambda *a: None)
by_name = {e['name']: e for e in metas}
ordered = [by_name[p.stem] for p in paths]
br.assemble(paths, run_dir, ordered, genre)
print('track ->', run_dir/'track.mp3')
