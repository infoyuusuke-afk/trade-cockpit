"""Replace one symbol's code in a COPY of the OWNER RSS workbook, touching only that symbol's row.

P0 RSS Excel 464A: 5595.T (QPS研究所) -> 464A.T (QPSホールディングス), row 89.

The workbook is never opened in Excel or re-saved by a spreadsheet library (that can drop
RSS/RTD extension data). The XLSX zip is rewritten part by part: every part except the four
below is copied with identical content, and inside those parts only the listed elements change.

  100銘柄RSS  row <row>    : code cell (shared string), name cell (shared string), every
                             "<old>.T" token in that row (RSS formulas + cached text)
  KIOXIA_JNX  row <row>    : code cell (shared string), every "<old>.T.JNX" token in that row
  sharedStrings.xml        : only the strings used by those three cells, edited in place; if any of
                             them is also used by another cell the run is BLOCKED (no new string is added)
  volatileDependencies.xml : only the RTD topics whose every reference is in that row of those
                             two sheets; topic code switched and cached value cleared so a stale
                             value of the old company can never be read as the new one

Anything unexpected (wrong old code/name in the row, a topic also used by another cell, an old
token outside the row, a token count different from the expected count) stops with BLOCKED and
no output file. It never writes to the source file.

usage:
  python scripts/v10_rss_workbook_code_swap.py SRC.xlsx OUT.xlsx --old 5595 --new 464A \
      --old-name "QPS研究所（5595）" --new-name "QPSホールディングス（464A）" --row 89 \
      [--expect-rss-formulas 32] [--expect-jnx-formulas 15] [--report report.json]
Exit 0 = PASS (OUT written), 1 = BLOCKED.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from xml.sax.saxutils import escape

RSS_SHEET = "100銘柄RSS"
JNX_SHEET = "KIOXIA_JNX"


class Blocked(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest().upper()


def sheet_parts(parts):
    wb = parts["xl/workbook.xml"].decode("utf-8")
    rels = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
    rid_target = dict(re.findall(r'<Relationship[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    rid_target.update({k: v for v, k in re.findall(r'<Relationship[^>]*Target="([^"]+)"[^>]*Id="([^"]+)"', rels)})
    out = {}
    for tag in re.findall(r"<sheet [^>]*/>", wb):
        name = re.search(r'name="([^"]+)"', tag).group(1)
        sid = re.search(r'sheetId="(\d+)"', tag).group(1)
        rid = re.search(r'r:id="([^"]+)"', tag).group(1)
        target = rid_target[rid].lstrip("/")
        out[name] = ("xl/" + target if not target.startswith("xl/") else target, sid)
    return out


def split_row(xml, row):
    m = re.search(r'<row r="%d"[ >].*?</row>' % row, xml, flags=re.S)
    if not m:
        raise Blocked(f"ROW_{row}_NOT_FOUND")
    return xml[:m.start()], m.group(0), xml[m.end():]


def cell(row_xml, ref):
    m = re.search(r'<c r="%s"[ >].*?(?:</c>|/>)' % ref, row_xml, flags=re.S)
    return m.group(0) if m else None


def shared_index(cell_xml):
    if not cell_xml or 't="s"' not in cell_xml:
        return None
    return int(re.search(r"<v>(\d+)</v>", cell_xml).group(1))


def sst_items(sst_xml):
    return list(re.finditer(r"<si>.*?</si>|<si/>", sst_xml, flags=re.S))


def sst_text(si):
    return "".join(re.findall(r"<t[^>]*>(.*?)</t>", si, flags=re.S))


def count_refs(parts, sheet_paths, idx):
    n = 0
    for p in sheet_paths:
        n += len(re.findall(r'<c [^>]*t="s"[^>]*><v>%d</v>' % idx, parts[p].decode("utf-8")))
    return n


def swap(src, out, old, new, old_name, new_name, row, exp_rss=None, exp_jnx=None):
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i.filename) for i in infos}
    rep = {"src": os.path.abspath(src), "src_sha256": sha256(src), "old": old, "new": new, "row": row}
    sheets = sheet_parts(parts)
    if RSS_SHEET not in sheets or JNX_SHEET not in sheets:
        raise Blocked("SHEET_NOT_FOUND")
    rss_path, rss_id = sheets[RSS_SHEET]
    jnx_path, jnx_id = sheets[JNX_SHEET]
    all_sheet_paths = [p for p, _ in sheets.values()]
    sst = parts["xl/sharedStrings.xml"].decode("utf-8")
    items = sst_items(sst)
    texts = [sst_text(m.group(0)) for m in items]

    old_t, new_t = f"{old}.T", f"{new}.T"
    old_j, new_j = f"{old}.T.JNX", f"{new}.T.JNX"

    # ---- 100銘柄RSS ----
    rss = parts[rss_path].decode("utf-8")
    pre, r_row, post = split_row(rss, row)
    if old_t in pre or old_t in post:
        raise Blocked("OLD_CODE_OUTSIDE_TARGET_ROW_100銘柄RSS")
    b_idx, c_idx = shared_index(cell(r_row, f"B{row}")), shared_index(cell(r_row, f"C{row}"))
    if b_idx is not None and texts[b_idx] == new_t:
        raise Blocked("ALREADY_SWAPPED_TARGET_ROW_HAS_NEW_CODE")
    if b_idx is None or texts[b_idx] != old_t:
        raise Blocked(f"B{row}_IS_NOT_{old_t}")
    if c_idx is None or texts[c_idx] != old_name:
        raise Blocked(f"C{row}_IS_NOT_OLD_NAME")
    rss_formulas = re.findall(r"<f>[^<]*</f>", r_row)
    rss_changed = sum(1 for f in rss_formulas if f'"{old_t}"' in f)
    if exp_rss is not None and rss_changed != exp_rss:
        raise Blocked(f"RSS_FORMULA_COUNT_{rss_changed}_NOT_{exp_rss}")
    new_r_row = r_row.replace(f'"{old_t}"', f'"{new_t}"')
    if old_t in re.sub(r"<v>\d+</v>", "", new_r_row):
        raise Blocked("OLD_CODE_LEFT_IN_RSS_ROW")
    parts[rss_path] = (pre + new_r_row + post).encode("utf-8")

    # ---- KIOXIA_JNX ----
    jnx = parts[jnx_path].decode("utf-8")
    pre, j_row, post = split_row(jnx, row)
    if old_j in pre or old_j in post or old_t in pre or old_t in post:
        raise Blocked("OLD_CODE_OUTSIDE_TARGET_ROW_KIOXIA_JNX")
    a_idx = shared_index(cell(j_row, f"A{row}"))
    if a_idx is None or texts[a_idx] != old_j:
        raise Blocked(f"JNX_A{row}_IS_NOT_{old_j}")
    jnx_changed = sum(1 for f in re.findall(r"<f>[^<]*</f>", j_row) if f'"{old_j}"' in f)
    if exp_jnx is not None and jnx_changed != exp_jnx:
        raise Blocked(f"JNX_FORMULA_COUNT_{jnx_changed}_NOT_{exp_jnx}")
    new_j_row = j_row.replace(f'"{old_j}"', f'"{new_j}"')
    if old_t in re.sub(r"<v>\d+</v>", "", new_j_row):
        raise Blocked("OLD_CODE_LEFT_IN_JNX_ROW")
    parts[jnx_path] = (pre + new_j_row + post).encode("utf-8")

    # ---- sharedStrings (only the three strings) ----
    edits = {b_idx: new_t, c_idx: new_name, a_idx: new_j}
    for idx, val in list(edits.items()):
        if count_refs(parts, all_sheet_paths, idx) != 1:
            raise Blocked(f"SHARED_STRING_{idx}_USED_BY_OTHER_CELLS")
    if any(escape(t) in texts or t in texts for t in (new_t, new_name, new_j)):
        raise Blocked("NEW_STRING_ALREADY_PRESENT")
    pieces, last = [], 0
    for i, m in enumerate(items):
        if i in edits:
            pieces.append(sst[last:m.start()])
            pieces.append(f"<si><t>{escape(edits[i])}</t></si>")
            last = m.end()
    pieces.append(sst[last:])
    parts["xl/sharedStrings.xml"] = "".join(pieces).encode("utf-8")

    # ---- volatileDependencies (RTD topics of that row only) ----
    vd_changed = 0
    if "xl/volatileDependencies.xml" in parts:
        vd = parts["xl/volatileDependencies.xml"].decode("utf-8")
        rtd_old = {f"{old}0.T": f"{new}0.T", old_j: new_j}

        def fix(m):
            nonlocal vd_changed
            tp = m.group(0)
            hits = [k for k in rtd_old if f"<stp>{k}</stp>" in tp]
            if not hits:
                return tp
            refs = re.findall(r'<tr r="[A-Z]+(\d+)" s="(\d+)"/>', tp)
            if not refs or any(int(r) != row or s not in (rss_id, jnx_id) for r, s in refs):
                raise Blocked("RTD_TOPIC_USED_OUTSIDE_TARGET_ROW")
            for k in hits:
                tp = tp.replace(f"<stp>{k}</stp>", f"<stp>{rtd_old[k]}</stp>")
            tp = re.sub(r"^<tp[^>]*>", '<tp t="s">', tp)
            tp = re.sub(r"<v>.*?</v>|<v/>", "<v/>", tp, count=1, flags=re.S)
            vd_changed += 1
            return tp

        vd2 = re.sub(r"<tp(?: [^>]*)?>.*?</tp>", fix, vd, flags=re.S)
        if old in vd2:
            raise Blocked("OLD_CODE_LEFT_IN_VOLATILE_DEPENDENCIES")
        parts["xl/volatileDependencies.xml"] = vd2.encode("utf-8")

    # ---- write a new zip, same part order / compression / timestamps ----
    tmp = out + ".partial"
    with zipfile.ZipFile(tmp, "w") as zo:
        for i in infos:
            zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
            zi.compress_type = i.compress_type
            zi.external_attr = i.external_attr
            zi.create_system = i.create_system
            zo.writestr(zi, parts[i.filename])
    os.replace(tmp, out)
    rep.update({"out": os.path.abspath(out), "out_sha256": sha256(out),
                "rss_formulas_changed": rss_changed, "jnx_formulas_changed": jnx_changed,
                "formulas_changed_total": rss_changed + jnx_changed,
                "shared_strings_changed": sorted(edits), "rtd_topics_changed": vd_changed,
                "changed_parts": [rss_path, jnx_path, "xl/sharedStrings.xml", "xl/volatileDependencies.xml"]})
    return rep


def verify_scope(src, out, row, rss_name=RSS_SHEET, jnx_name=JNX_SHEET):
    """Independent re-read: every part identical except the allowed ones, and inside them only the target row."""
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        na, nb = [i.filename for i in a.infolist()], [i.filename for i in b.infolist()]
        res = {"same_part_list_and_order": na == nb}
        pa = {n: a.read(n) for n in na}
        pb = {n: b.read(n) for n in nb}
    sheets = sheet_parts(pa)
    allowed = {sheets[rss_name][0], sheets[jnx_name][0], "xl/sharedStrings.xml", "xl/volatileDependencies.xml"}
    res["changed_parts"] = sorted(n for n in na if pa[n] != pb.get(n))
    res["unexpected_changed_parts"] = sorted(set(res["changed_parts"]) - allowed)
    for name in (rss_name, jnx_name):
        p = sheets[name][0]
        x1, r1, y1 = split_row(pa[p].decode("utf-8"), row)
        x2, r2, y2 = split_row(pb[p].decode("utf-8"), row)
        res[f"{name}_outside_row_identical"] = (x1 == x2 and y1 == y2)
    res["rtd_changes_only_target_row"] = True
    if "xl/volatileDependencies.xml" in pa:
        rss_id, jnx_id = sheets[rss_name][1], sheets[jnx_name][1]
        t1 = re.findall(r"<tp(?: [^>]*)?>.*?</tp>", pa["xl/volatileDependencies.xml"].decode("utf-8"), flags=re.S)
        t2 = re.findall(r"<tp(?: [^>]*)?>.*?</tp>", pb["xl/volatileDependencies.xml"].decode("utf-8"), flags=re.S)
        res["rtd_topic_count_same"] = len(t1) == len(t2)
        for u, v in zip(t1, t2):
            if u != v:
                refs = re.findall(r'<tr r="[A-Z]+(\d+)" s="(\d+)"/>', v)
                if not refs or any(int(r) != row or sid not in (rss_id, jnx_id) for r, sid in refs):
                    res["rtd_changes_only_target_row"] = False
        if not res["rtd_topic_count_same"]:
            res["rtd_changes_only_target_row"] = False
    s1, s2 = sst_items(pa["xl/sharedStrings.xml"].decode()), sst_items(pb["xl/sharedStrings.xml"].decode())
    res["shared_strings_count_same"] = len(s1) == len(s2)
    res["shared_strings_changed_idx"] = [i for i, (u, v) in enumerate(zip(s1, s2)) if u.group(0) != v.group(0)]
    res["ok"] = (res["same_part_list_and_order"] and not res["unexpected_changed_parts"]
                 and res[f"{rss_name}_outside_row_identical"] and res[f"{jnx_name}_outside_row_identical"]
                 and res["shared_strings_count_same"] and res["rtd_changes_only_target_row"])
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--old-name", required=True)
    ap.add_argument("--new-name", required=True)
    ap.add_argument("--row", type=int, required=True)
    ap.add_argument("--expect-rss-formulas", type=int)
    ap.add_argument("--expect-jnx-formulas", type=int)
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    if os.path.abspath(a.src) == os.path.abspath(a.out):
        print(json.dumps({"result": "BLOCKED", "reason": "OUT_MUST_DIFFER_FROM_SRC"}))
        return 1
    try:
        rep = swap(a.src, a.out, a.old, a.new, a.old_name, a.new_name, a.row, a.expect_rss_formulas, a.expect_jnx_formulas)
        rep["scope_check"] = verify_scope(a.src, a.out, a.row)
        rep["result"] = "PASS" if rep["scope_check"]["ok"] else "BLOCKED"
        if rep["result"] != "PASS":
            os.remove(a.out)
    except Blocked as e:
        rep = {"result": "BLOCKED", "reason": str(e)}
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False))
    return 0 if rep["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
