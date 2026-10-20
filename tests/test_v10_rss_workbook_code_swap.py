"""One-row code swap in a COPY of the RSS workbook (P0 RSS Excel 464A).

Synthetic workbooks only, built here with the same layout as the OWNER file: hidden
100銘柄RSS / KIOXIA_JNX sheets, shared strings for the code/name cells, RSS formulas,
an RTD volatileDependencies part and a log sheet that also mentions the old code.
No real workbook, prices or PC paths.
"""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("swap", ROOT / "scripts" / "v10_rss_workbook_code_swap.py")
swap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(swap)

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ITEMS = ["現在値", "前日終値", "出来高"]
ROW = 5


def build(path, codes, log_mentions_old=True, extra_old_cell=False, shared_name_twice=False):
    strings = []

    def s(t):
        strings.append(t)
        return len(strings) - 1

    rss_rows, jnx_rows, tps = [], [], []
    for r, code in enumerate(codes, start=2):
        name = f"合成（{code[:-2]}）"
        cells = f'<c r="A{r}"><v>{r - 1}</v></c><c r="B{r}" t="s"><v>{s(code)}</v></c><c r="C{r}" t="s"><v>{s(name)}</v></c>'
        for k, it in enumerate(ITEMS):
            col = "EFG"[k]
            cells += f'<c r="{col}{r}" t="str"><f>_xll.RssMarket("{code}","{it}")</f></c>'
            tps.append(f'<tp><v>{100 + r}</v><stp/><stp>Market</stp><stp>STOCK</stp><stp>{code[:-2]}0.T</stp><stp>{it}</stp><tr r="{col}{r}" s="6"/></tp>')
        cells += f'<c r="H{r}" t="str"><f>_xll.RssMarginInfo("{code}","売建可能数量")</f><v>=@RssMarginInfo("{code}","売建可能数量") =&gt;</v></c>'
        rss_rows.append(f'<row r="{r}">{cells}</row>')
        jc = f'<c r="A{r}" t="s"><v>{s(code + ".JNX")}</v></c><c r="B{r}" t="str"><f>_xll.RssMarket("{code}.JNX","現在値")</f></c>'
        tps.append(f'<tp t="s"><v/><stp/><stp>Market</stp><stp>STOCK</stp><stp>{code}.JNX</stp><stp>現在値</stp><tr r="B{r}" s="7"/></tp>')
        jnx_rows.append(f'<row r="{r}">{jc}</row>')
    if extra_old_cell:
        rss_rows.append(f'<row r="200"><c r="E200" t="str"><f>_xll.RssMarket("{codes[ROW - 2]}","現在値")</f></c></row>')
    if shared_name_twice:
        rss_rows.append(f'<row r="201"><c r="C201" t="s"><v>{strings.index(f"合成（{codes[ROW - 2][:-2]}）")}</v></c></row>')
    log = f'<row r="2"><c r="A2" t="inlineStr"><is><t>{codes[ROW - 2] if log_mentions_old else "x"} 過去の記録</t></is></c></row>'
    sst = "".join(f"<si><t>{t}</t></si>" for t in strings)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{M}" xmlns:r="{R}"><sheets>'
                   '<sheet name="100銘柄RSS" sheetId="6" state="hidden" r:id="rId1"/>'
                   '<sheet name="KIOXIA_JNX" sheetId="7" state="hidden" r:id="rId2"/>'
                   '<sheet name="検証ログ" sheetId="4" r:id="rId3"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="w" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="w" Target="worksheets/sheet2.xml"/>'
                   '<Relationship Id="rId3" Type="w" Target="worksheets/sheet3.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{M}"><sheetData>{"".join(rss_rows)}</sheetData></worksheet>')
        z.writestr("xl/worksheets/sheet2.xml", f'<worksheet xmlns="{M}"><sheetData>{"".join(jnx_rows)}</sheetData></worksheet>')
        z.writestr("xl/worksheets/sheet3.xml", f'<worksheet xmlns="{M}"><sheetData>{log}</sheetData></worksheet>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{M}" count="{len(strings)}" uniqueCount="{len(strings)}">{sst}</sst>')
        z.writestr("xl/volatileDependencies.xml", f'<volTypes xmlns="{M}"><volType type="realTimeData"><main first="rtd">{"".join(tps)}</main></volType></volTypes>')


class RssWorkbookCodeSwap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.codes = ["%04d.T" % (1000 + i) for i in range(8)]
        self.codes[ROW - 2] = "5595.T"

    def tearDown(self):
        self.tmp.cleanup()

    def run_swap(self, **kw):
        src, out = self.d / "src.xlsx", self.d / "out.xlsx"
        build(src, self.codes, **kw)
        before = src.read_bytes()
        rc = swap.main([str(src), str(out), "--old", "5595", "--new", "464A", "--old-name", "合成（5595）",
                        "--new-name", "QPSホールディングス（464A）", "--row", str(ROW),
                        "--expect-rss-formulas", str(len(ITEMS) + 1), "--expect-jnx-formulas", "1",
                        "--report", str(self.d / "rep.json")])
        self.assertEqual(src.read_bytes(), before, "source must never be written")
        return rc, src, out

    def test_swaps_only_target_row_and_keeps_everything_else(self):
        rc, src, out = self.run_swap()
        self.assertEqual(rc, 0)
        with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
            self.assertEqual([i.filename for i in a.infolist()], [i.filename for i in b.infolist()])
            self.assertEqual(a.read("xl/worksheets/sheet3.xml"), b.read("xl/worksheets/sheet3.xml"))  # log untouched
            rss = b.read("xl/worksheets/sheet1.xml").decode()
            jnx = b.read("xl/worksheets/sheet2.xml").decode()
            sst = b.read("xl/sharedStrings.xml").decode()
            vd = b.read("xl/volatileDependencies.xml").decode()
            wb = b.read("xl/workbook.xml").decode()
        self.assertNotIn("5595", rss + jnx + sst + vd)
        self.assertEqual(rss.count('"464A.T"'), len(ITEMS) + 2)  # formulas + margin formula + cached text
        self.assertEqual(jnx.count('"464A.T.JNX"'), 1)
        self.assertIn("<t>464A.T</t>", sst)
        self.assertIn("<t>QPSホールディングス（464A）</t>", sst)
        self.assertIn("<t>464A.T.JNX</t>", sst)
        self.assertIn("<stp>464A0.T</stp>", vd)
        # stale RTD value of the old company is cleared for the swapped topics only
        self.assertNotIn(f"<v>{100 + ROW}</v><stp/><stp>Market</stp><stp>STOCK</stp><stp>464A0.T</stp>", vd)
        self.assertIn(f"<v>{100 + ROW + 1}</v>", vd)
        self.assertIn('state="hidden"', wb)

    def test_verify_scope_reports_only_allowed_parts(self):
        rc, src, out = self.run_swap()
        res = swap.verify_scope(str(src), str(out), ROW)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["unexpected_changed_parts"], [])
        self.assertEqual(len(res["shared_strings_changed_idx"]), 3)

    def test_old_code_outside_target_row_blocks(self):
        rc, src, out = self.run_swap(extra_old_cell=True)
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())

    def test_shared_name_used_by_another_cell_blocks(self):
        rc, src, out = self.run_swap(shared_name_twice=True)
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())

    def test_wrong_row_blocks(self):
        src, out = self.d / "src.xlsx", self.d / "out.xlsx"
        build(src, self.codes)
        rc = swap.main([str(src), str(out), "--old", "5595", "--new", "464A", "--old-name", "合成（5595）",
                        "--new-name", "QPSホールディングス（464A）", "--row", str(ROW + 1)])
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())

    def test_same_src_and_out_refused(self):
        src = self.d / "src.xlsx"
        build(src, self.codes)
        rc = swap.main([str(src), str(src), "--old", "5595", "--new", "464A", "--old-name", "合成（5595）",
                        "--new-name", "x", "--row", str(ROW)])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
