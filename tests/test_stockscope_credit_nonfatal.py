import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stockscope_credit", ROOT / "scripts" / "stockscope_credit.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)


class NonFatal(unittest.TestCase):
    """A blocked or broken StockScope read must not stop the whole data update (update.yml runs the scripts in one step)."""

    def _run(self, exc, tmp="credit_supply_test.json"):
        out = ROOT / "tests" / tmp
        out.write_text('{"keep": true}\n', encoding="utf-8")
        try:
            with mock.patch.object(sc, "OUT", out), mock.patch.object(sc, "urlopen", side_effect=exc):
                sc.main()   # must not raise
            self.assertEqual(out.read_text(encoding="utf-8"), '{"keep": true}\n')
        finally:
            out.unlink()

    def test_http_403_keeps_previous_file(self):
        self._run(HTTPError(sc.URL, 403, "Forbidden", {}, None))

    def test_network_error_keeps_previous_file(self):
        self._run(URLError("down"))

    def test_bad_page_keeps_previous_file(self):
        self._run(ValueError("missing StockScope field"))


if __name__ == "__main__":
    unittest.main()
