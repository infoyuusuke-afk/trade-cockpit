"""D-045 synthetic-only negative/positive acceptance; never reads market data."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
from pathlib import Path
import os
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ms2_live" / "d045_futures_index_record.py"
PS = ROOT / "ms2_live" / "D045_FuturesIndex_Recorder.ps1"
spec = importlib.util.spec_from_file_location("d045_private", MODULE)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 22, 19, 0, 11, tzinfo=JST)


def snapshot(now=NOW):
    ids = ["N225_MINI_F", "TOPIX_F", "GROWTH250_F",
           "N225_I", "TOPIX_I", "GROWTH250_I"]
    codes = ["123456789", "234567891", "345678912", "N225", "TOPX", "MTHR"]
    rows = []
    for i, ident in enumerate(ids):
        fut = i < 3
        rows.append({
            "instrument_id": ident, "kind": "FOP" if fut else "INDEX",
            "symbol": codes[i], "contract_month": "202612" if fut else None,
            "source_date": now.strftime("%Y/%m/%d"),
            "source_time": now.strftime("%H:%M:%S" if fut else "%H:%M"),
            "price": 40000.5 + i, "volume": 12300 + i,
            "vwap": 39990.5 if fut else None,
            "best_bid": 39998.0 if fut else None,
            "best_ask": 40001.0 if fut else None,
            "best_bid_size": 52 if fut else None,
            "best_ask_size": 73 if fut else None,
        })
    return {"schema_version": d.SCHEMA, "observed_at_jst": now.isoformat(),
            "rows": rows, "real_submit_allowed": False}


class D045OfflineValidation(unittest.TestCase):
    def test_six_series_resolve_expected_symbols_and_precision(self):
        v, bad = d.validate_snapshot(snapshot(), now=NOW)
        self.assertEqual(len(v), 6)
        self.assertEqual(bad, [])
        self.assertEqual({x["instrument_id"] for x in v}, set(d.EXPECTED))
        self.assertEqual({x["source_precision"] for x in v if x["kind"] == "FOP"}, {"SECOND"})
        self.assertEqual({x["source_precision"] for x in v if x["kind"] == "INDEX"}, {"MINUTE"})
        for x in v:
            self.assertEqual(x["source_time_verified"], "UNVERIFIED")
            self.assertEqual(x["real_time_verified"], "UNVERIFIED")
            self.assertEqual(x["real_submit_allowed"], "false")

    def test_six_series_missing_or_duplicate_blocks_snapshot(self):
        s = snapshot()
        s["rows"].append(copy.deepcopy(s["rows"][-1]))
        with self.assertRaisesRegex(d.Blocked, "SIX_SERIES_UNIVERSE_INVALID"):
            d.validate_snapshot(s, now=NOW)

    def test_empty_futures_code_is_rejected_without_changing_other_rows(self):
        s = snapshot()
        s["rows"][0]["symbol"] = "#N/A"
        valid, rejected = d.validate_snapshot(s, now=NOW)
        self.assertEqual(len(valid), 5)
        self.assertEqual(rejected, [{"instrument_id":"N225_MINI_F","reason":"FOP_CODE_UNVERIFIED"}])

    def test_growth_index_code_not_misidentified_as_futures_code(self):
        s = snapshot()
        s["rows"][5]["symbol"] = "MOTF"
        v, bad = d.validate_snapshot(s, now=NOW)
        self.assertEqual(len(v), 5)
        self.assertEqual(bad[0]["reason"], "INDEX_CODE_OR_MONTH_INVALID")
        s["rows"][5]["symbol"] = "MTHR"
        self.assertEqual(len(d.validate_snapshot(s, now=NOW)[0]), 6)

    def test_time_precision_and_future_time_fail_closed(self):
        s = snapshot()
        s["rows"][3]["source_time"] = "19:00:11"  # index only HH:MM
        v, bad = d.validate_snapshot(s, now=NOW)
        self.assertEqual(len(v), 5)
        self.assertEqual(bad[0]["reason"], "SOURCE_TIME_PRECISION_INVALID")
        s = snapshot()
        s["rows"][0]["source_time"] = "19:02:11"
        v, bad = d.validate_snapshot(s, now=NOW)
        self.assertEqual(bad[0]["reason"], "FUTURE_SOURCE_EVENT")

    def test_invalid_fields_and_unavailable_value_never_fabricated(self):
        s = snapshot()
        s["rows"][0]["price"] = None
        s["rows"][1]["volume"] = "#N/A"
        s["rows"][2]["vwap"] = -1
        s["rows"][4]["vwap"] = 9
        valid, bad = d.validate_snapshot(s, now=NOW)
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(bad), 4)

    def test_stale_and_month_rollover_stop(self):
        s = snapshot()
        s["rows"][0]["contract_month"] = "202609"
        v, bad = d.validate_snapshot(s, now=NOW)
        self.assertEqual(bad[0]["reason"], "EXPIRED_CONTRACT_MONTH")
        s = snapshot()
        s["rows"][1]["source_date"] = "2026/10/18"
        v, bad = d.validate_snapshot(s, now=NOW)
        self.assertEqual(bad[0]["reason"], "SOURCE_EVENT_TOO_OLD")

    def test_unknown_snapshot_keys_banned_and_submit_false_required(self):
        s = snapshot()
        s["real_submit_allowed"] = True
        with self.assertRaisesRegex(d.Blocked, "SNAPSHOT_SAFETY_INVALID"):
            d.validate_snapshot(s, now=NOW)
        s = snapshot()
        s["order_allowed"] = True
        with self.assertRaisesRegex(d.Blocked, "SNAPSHOT_SCHEMA_INVALID"):
            d.validate_snapshot(s, now=NOW)

    def test_local_append_dedup_restart_with_private_permissions(self):
        s = snapshot()
        records, invalid = d.validate_snapshot(s, now=NOW)
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root, 0o700)
            self.assertEqual(d.append_records(root, s, records), 6)
            self.assertEqual(d.append_records(root, s, records), 0)
            path = Path(root) / "2026-10-22" / d.OUTPUT
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 7)
            self.assertNotIn("2026/10/21", path.read_text(encoding="utf-8"))
            s2 = snapshot()
            s2["rows"][2]["price"] = 50000.0
            r2, _ = d.validate_snapshot(s2, now=NOW)
            self.assertEqual(d.append_records(root, s2, r2), 1)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 8)

    def test_symlink_and_foreign_checkout_rejected(self):
        s = snapshot()
        records, _ = d.validate_snapshot(s, now=NOW)
        with tempfile.TemporaryDirectory() as tmp:
            safe = Path(tmp) / "private"
            safe.mkdir(mode=0o700)
            os.chmod(safe, 0o700)
            alias = Path(tmp) / "link"
            if hasattr(os, "symlink"):
                try:
                    alias.symlink_to(safe)
                except OSError:
                    pass
                else:
                    with self.assertRaisesRegex(d.Blocked, "SYMLINK"):
                        d.append_records(str(alias), s, records)
            with self.assertRaisesRegex(d.Blocked, "INSIDE_GITHUB_REPOSITORY"):
                d._private_root(str(ROOT))

    def test_cli_paid_like_write_requires_three_gates(self):
        import json
        payload = json.dumps(snapshot(), ensure_ascii=False).encode("utf-8")
        cmd = [sys.executable, str(MODULE), "--write"]
        p = subprocess.run(cmd, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        self.assertEqual(p.returncode, 3)
        self.assertIn(b"D019_D035_OWNER_RELEASE_GATE_NOT_MET", p.stdout)
        self.assertNotIn(b"40000.5", p.stdout)

    def test_powershell_sheet_generator_is_explicit_and_never_launches_excel(self):
        src = PS.read_text(encoding="utf-8")
        for name in ("N225MF", "TOPXF", "MOTF", "N225", "TOPX", "MTHR",
                     "RssFOPCode", "RssFOPMarket", "RssIndexMarket",
                     "D045_FUTURES_INDEX", "D045_PROBE",
                     "GetActiveObject", "D019_D035_OWNER_RELEASE_GATE_NOT_MET",
                     "D023_REQUIRES_EXACTLY_ONE_EXCEL_PROCESS"):
            self.assertIn(name, src)
        for forbidden in (".Save()", ".Quit()", "Workbooks.Add(",
                          "RssFOPOpenOrder", "RssFOPCloseOrder",
                          "RssOrder", "Start-Process EXCEL"):
            self.assertNotIn(forbidden, src)

    @unittest.skipUnless(sys.platform == "win32", "Windows PowerShell 5.1 parser only")
    def test_powershell_ast_has_zero_errors(self):
        import shutil
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("powershell.exe unavailable")
        ps_path = str(PS).replace("'", "''")
        ps = (
            "$t=$null;$e=$null;"
            "$a=[Management.Automation.Language.Parser]::ParseFile('" + ps_path + "',[ref]$t,[ref]$e);"
            "if($e.Count){$e|Out-String|Write-Host;exit 1};"
            "if($null -eq $a){exit 2};'D045_PARSER_PASS'"
        )
        p = subprocess.run([exe, "-NoProfile", "-Command", ps],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=20)
        self.assertEqual(p.returncode, 0, p.stdout.decode(errors="replace") + p.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
