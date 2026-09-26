"""CLI output encoding is UTF-8 on every platform (Windows cp932 regression)."""
import io
import sys
import unittest
from unittest import mock

from auto_publish import cli


class TestCliUtf8Output(unittest.TestCase):
    def test_cp932_stdout_is_reconfigured_to_utf8(self):
        out_buf, err_buf = io.BytesIO(), io.BytesIO()
        fake_out = io.TextIOWrapper(out_buf, encoding="cp932")
        fake_err = io.TextIOWrapper(err_buf, encoding="cp932")
        with mock.patch.object(sys, "stdout", fake_out), mock.patch.object(sys, "stderr", fake_err):
            with self.assertRaises(UnicodeEncodeError):
                print("¥")  # what used to happen on Windows
            cli._utf8_stdio()
            print("It closed at ¥2,345 — 終値")
            print("err ¥", file=sys.stderr)
            fake_out.flush()
            fake_err.flush()
        self.assertEqual(out_buf.getvalue(), "It closed at ¥2,345 — 終値\n".encode("utf-8"))
        self.assertEqual(err_buf.getvalue(), "err ¥\n".encode("utf-8"))

    def test_json_content_unchanged(self):
        out_buf = io.BytesIO()
        fake_out = io.TextIOWrapper(out_buf, encoding="cp932")
        with mock.patch.object(sys, "stdout", fake_out):
            cli._utf8_stdio()
            cli._out({"ok": True, "result": {"text": "¥100"}})
            fake_out.flush()
        self.assertEqual(out_buf.getvalue().decode("utf-8"),
                         '{\n  "ok": true,\n  "result": {\n    "text": "¥100"\n  }\n}\n')


if __name__ == "__main__":
    unittest.main()
