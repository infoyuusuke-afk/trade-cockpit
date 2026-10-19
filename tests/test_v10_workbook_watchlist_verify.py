"""Read-only cutover verifier for the OWNER workbook vs the V10 watchlist.

Synthetic workbooks only (built here as minimal .xlsx zips); no real
workbook, prices or paths. The verifier must PASS only when the
100銘柄RSS codes match the watchlist exactly and no forbidden code remains.
"""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vwb", ROOT / "scripts" / "verify_v10_workbook_watchlist.py")
vwb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vwb)

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _codes(n=100):
    return ["%04d.T" % (1000 + i) for i in range(n)]


def _sheet(rows):
    out = []
    for r, (code, formula_code) in enumerate(rows, start=2):
        cells = '<c r="A%d"><v>%d</v></c>' % (r, r - 1)
        cells += '<c r="B%d" t="inlineStr"><is><t>%s</t></is></c>' % (r, escape(code))
        cells += '<c r="E%d" t="str"><f>_xll.RssMarket("%s","現在値")</f><v></v></c>' % (r, escape(formula_code))
        out.append('<row r="%d">%s</row>' % (r, cells))
    return ('<worksheet xmlns="%s"><sheetData><row r="1"><c r="B1" t="inlineStr"><is><t>コード</t></is></c></row>%s'
            '</sheetData></worksheet>') % (MAIN_NS, "".join(out))


def _write_wb(path, rows, jnx_codes=()):
    jnx = '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (MAIN_NS, "".join(
        '<row r="%d"><c r="A%d" t="str"><f>_xll.RssMarket("%s.JNX","現在値")</f><v></v></c></row>' % (i + 1, i + 1, escape(c))
        for i, c in enumerate(jnx_codes)))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml",
                   '<workbook xmlns="%s" xmlns:r="%s"><sheets>'
                   '<sheet name="100銘柄RSS" sheetId="1" r:id="rId1"/>'
                   '<sheet name="KIOXIA_JNX" sheetId="2" r:id="rId2"/></sheets></workbook>' % (MAIN_NS, REL_NS))
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="x" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", _sheet(rows))
        z.writestr("xl/worksheets/sheet2.xml", jnx)


def _write_wl(path, codes):
    stocks = {"合成%03d" % i: {"ticker": c, "sector": "synthetic", "style": "both"} for i, c in enumerate(codes)}
    Path(path).write_text(json.dumps({"stocks": stocks}, ensure_ascii=False), encoding="utf-8")


class WorkbookWatchlistVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.codes = _codes()
        self.codes[87] = "464A.T"
        self.wl = self.dir / "wl.json"
        _write_wl(self.wl, self.codes)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, rows, jnx=(), forbid=("5595.T",)):
        wb = self.dir / "wb.xlsx"
        _write_wb(wb, rows, jnx)
        return vwb.check(str(wb), str(self.wl), list(forbid))

    def test_matching_workbook_passes(self):
        out = self._run([(c, c) for c in self.codes], jnx=["285A.T", "464A.T"])
        self.assertEqual(out["result"], "PASS", out)
        self.assertEqual(out["row89_code"], "464A.T")

    def test_row89_not_switched_fails(self):
        rows = [(c, c) for c in self.codes]
        rows[87] = ("5595.T", "5595.T")
        out = self._run(rows)
        self.assertEqual(out["result"], "FAIL")
        self.assertIn("SHEET_CODE_ORDER_MISMATCH", out["failures"])
        self.assertIn("FORBIDDEN_CODE_PRESENT", out["failures"])
        self.assertEqual(out["order_mismatch_rows"], [89])

    def test_code_switched_but_formula_not_fails(self):
        rows = [(c, c) for c in self.codes]
        rows[87] = ("464A.T", "5595.T")
        out = self._run(rows)
        self.assertIn("ROW_FORMULA_CODE_MISMATCH", out["failures"])

    def test_jnx_left_on_old_code_fails(self):
        out = self._run([(c, c) for c in self.codes], jnx=["5595.T"])
        self.assertIn("FORBIDDEN_CODE_PRESENT", out["failures"])

    def test_duplicate_and_short_sheet_fail(self):
        rows = [(c, c) for c in self.codes]
        rows[5] = (rows[4][0], rows[4][0])
        self.assertIn("SHEET_NOT_100_UNIQUE", self._run(rows)["failures"])
        self.assertIn("SHEET_NOT_100_UNIQUE", self._run([(c, c) for c in self.codes[:99]])["failures"])

    def test_reordered_sheet_fails(self):
        rows = [(c, c) for c in self.codes]
        rows[1], rows[2] = rows[2], rows[1]
        self.assertIn("SHEET_CODE_ORDER_MISMATCH", self._run(rows)["failures"])

    def test_cli_exit_codes(self):
        wb = self.dir / "cli.xlsx"
        _write_wb(wb, [(c, c) for c in self.codes])
        self.assertEqual(vwb.main(["x", str(wb), str(self.wl), "--forbid", "5595.T"]), 0)
        rows = [(c, c) for c in self.codes]
        rows[87] = ("5595.T", "5595.T")
        _write_wb(wb, rows)
        self.assertEqual(vwb.main(["x", str(wb), str(self.wl), "--forbid", "5595.T"]), 1)


if __name__ == "__main__":
    unittest.main()
