"""Свежепересозданный runner-контейнер не содержит ручных пакетов (unbreak t_5cdbb967):
каждый workflow, проверяющий ffmpeg, обязан сам уметь его поставить."""
import glob, os, re
import unittest
WDIR = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows")
FALLBACK = re.compile(r"apt-get install -y[^&|;]*ffmpeg", re.I)
class TestWorkflowFfmpegSelfinstall(unittest.TestCase):
    def test_every_ffmpeg_check_has_install_fallback(self):
        broken = []
        for f in sorted(glob.glob(os.path.join(WDIR, "*.y*ml"))):
            txt = open(f, encoding="utf-8").read()
            if "command -v ffmpeg" in txt and not FALLBACK.search(txt):
                broken.append(os.path.basename(f))
        self.assertEqual(broken, [], f"workflow без установки ffmpeg: {broken}")
if __name__ == "__main__":
    unittest.main()
