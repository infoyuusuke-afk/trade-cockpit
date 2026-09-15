import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import upcoming_earnings as earnings


class EarningsTests(unittest.TestCase):
    def test_company_table_numeric_and_alphanumeric_codes(self):
        html = "<table><tr><th>コード</th><th>会社名</th></tr><tr><td>7203</td><td>A</td></tr><tr><td>285A</td><td>B</td></tr></table>"
        self.assertEqual(earnings.parse_companies(html), [
            {"code": "7203", "name": "A"}, {"code": "285A", "name": "B"}])

    def run_empty_source(self, rendered):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(earnings, "OUT", root / "output.json"), \
                 patch.object(earnings, "LOG_PATH", root / "history.json"), \
                 patch.object(earnings, "load_watch_universe", return_value=set()), \
                 patch.object(earnings, "fetch_html", return_value="<html></html>"), \
                 patch.object(earnings, "fetch_html_rendered", return_value=rendered) as fallback:
                code = 0
                try:
                    earnings.main()
                except SystemExit as exc:
                    code = exc.code
                fallback.assert_called_once()
                return code, json.loads((root / "output.json").read_text(encoding="utf-8"))

    def test_official_empty_notice_is_success(self):
        code, result = self.run_empty_source("<html>翌営業日の開示予定会社はございません</html>")
        self.assertEqual(code, 0)
        self.assertIsNone(result["fetch_error"])
        self.assertEqual(result["picks"], [])
        self.assertTrue(any(d.get("status") == "confirmed_empty" for d in result["diagnostics"]))

    def test_unknown_page_is_failure_not_empty_success(self):
        code, result = self.run_empty_source("<html>Unexpected page</html>")
        self.assertEqual(code, 1)
        self.assertIn("RuntimeError", result["fetch_error"])

    def test_network_exception_is_nonzero_and_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(earnings, "OUT", root / "output.json"), \
                 patch.object(earnings, "LOG_PATH", root / "history.json"), \
                 patch.object(earnings, "load_watch_universe", return_value=set()), \
                 patch.object(earnings, "fetch_html", side_effect=TimeoutError("test timeout")):
                with self.assertRaises(SystemExit) as failure:
                    earnings.main()
                self.assertEqual(failure.exception.code, 1)
                result = json.loads((root / "output.json").read_text(encoding="utf-8"))
                self.assertEqual(result["fetch_error"], "TimeoutError: test timeout")


if __name__ == "__main__":
    unittest.main()
