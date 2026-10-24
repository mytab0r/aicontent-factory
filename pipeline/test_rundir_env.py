import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_new_and_latest_honor_acf_run_dir():
    import common
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td) / "runs" / "40104157738"
        os.environ["ACF_RUN_DIR"] = str(rd)
        try:
            d = common.new_run_dir()
            assert d == rd and rd.exists(), d
            (rd / "cover.png").write_text("x")
            assert common.latest_run_dir() == rd
        finally:
            os.environ.pop("ACF_RUN_DIR", None)

def test_latest_without_env_is_newest():
    import common
    os.environ.pop("ACF_RUN_DIR", None)
    old = common.RUNS_DIR
    with tempfile.TemporaryDirectory() as td:
        common.RUNS_DIR = Path(td)
        (Path(td) / "20261024_000000").mkdir()
        (Path(td) / "20261025_000000").mkdir()
        assert common.latest_run_dir().name == "20261025_000000"
    common.RUNS_DIR = old
