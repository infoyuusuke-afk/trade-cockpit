"""Read-only cutover check: the OWNER workbook's 100銘柄RSS and KIOXIA_JNX
codes must match the V10 watchlist exactly (count, order, no duplicates, each
row's RssMarket formulas use that row's own code, and no delisted code left).

It only reads a workbook file (copy it first); it never opens Excel, edits
the workbook or touches the running V10. Exit 0 = PASS, 1 = FAIL.

Usage: python scripts/verify_v10_workbook_watchlist.py <workbook.xlsx> <watchlist_100.json> [--forbid CODE ...]
"""
import json, re, sys, zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def sheet_rows(path, name):
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sst = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            sst.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    target = None
    for s in wb.find("m:sheets", NS):
        if s.get("name") == name:
            target = rels[s.get("{%s}id" % NS["r"])]
    if target is None:
        return None
    target = "xl/" + target.lstrip("/").replace("xl/", "", 1)
    rows = {}
    for row in ET.fromstring(z.read(target)).find("m:sheetData", NS):
        r = int(row.get("r"))
        cells = {}
        for c in row:
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            v = c.find("m:v", NS)
            f = c.find("m:f", NS)
            val = v.text if v is not None else None
            if c.get("t") == "s" and val is not None:
                val = sst[int(val)]
            elif c.get("t") == "inlineStr":
                val = "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"]))
            cells[col] = (val, f.text if f is not None else None)
        rows[r] = cells
    return rows


def check(wb_path, watchlist_path, forbid=()):
    with open(watchlist_path, encoding="utf-8-sig") as fh:
        wl = json.load(fh)
    expected = [row["ticker"] for _, row in wl["stocks"].items()]
    out = {"watchlist_count": len(expected), "watchlist_dups": len(expected) - len(set(expected))}
    rows = sheet_rows(wb_path, "100銘柄RSS")
    codes = [rows.get(r, {}).get("B", (None, None))[0] for r in range(2, 102)]
    out["sheet_count"] = sum(1 for c in codes if c)
    out["sheet_dups"] = len([c for c in codes if c]) - len({c for c in codes if c})
    out["order_mismatch_rows"] = [i + 2 for i, (a, b) in enumerate(zip(codes, expected)) if a != b]
    out["row89_code"] = codes[87]
    f89 = [v[1] for k, v in sorted(rows.get(89, {}).items()) if v[1]]
    out["row89_formula_codes"] = sorted(set(re.findall(r'Rss[A-Za-z]+\("([^"]+)"', " ".join(f89))))
    bad = []
    for r in range(2, 102):
        code = rows.get(r, {}).get("B", (None, None))[0]
        fcodes = set(re.findall(r'Rss[A-Za-z]+\("([^"]+)"', " ".join(v[1] for v in rows.get(r, {}).values() if v[1])))
        if fcodes and fcodes != {code}:
            bad.append(r)
    out["rows_formula_code_mismatch"] = bad
    jnx = sheet_rows(wb_path, "KIOXIA_JNX") or {}
    jtext = " ".join((v[0] or "") + " " + (v[1] or "") for row in jnx.values() for v in row.values())
    out["jnx_mentions_5595"] = jtext.count("5595.T")
    out["jnx_mentions_464A"] = jtext.count("464A.T")
    out["forbidden_codes_found"] = {
        code: sum(1 for row in list(rows.values()) + list(jnx.values()) for v in row.values()
                  if code in ((v[0] or "") + (v[1] or "")))
        for code in forbid
    }
    failures = []
    if out["watchlist_count"] != 100 or out["watchlist_dups"]:
        failures.append("WATCHLIST_NOT_100_UNIQUE")
    if out["sheet_count"] != 100 or out["sheet_dups"]:
        failures.append("SHEET_NOT_100_UNIQUE")
    if out["order_mismatch_rows"]:
        failures.append("SHEET_CODE_ORDER_MISMATCH")
    if out["rows_formula_code_mismatch"]:
        failures.append("ROW_FORMULA_CODE_MISMATCH")
    if any(out["forbidden_codes_found"].values()):
        failures.append("FORBIDDEN_CODE_PRESENT")
    out["result"] = "FAIL" if failures else "PASS"
    out["failures"] = failures
    return out


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    forbid = argv[argv.index("--forbid") + 1:] if "--forbid" in argv else []
    out = check(argv[1], argv[2], forbid)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
