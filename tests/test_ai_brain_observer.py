"""Independent BRAIN observation must never become an execution signal."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from scripts.ai_brain_observer import analyze, run_once, status_snapshot

NOW=datetime(2026,10,16,0,20,0,tzinfo=timezone.utc)
def source():
    return {
        "schema_version":"ms2-common-1.0",
        "source":"MarketSpeed II RSS / local PC",
        "source_mode":"MS2_RSS_WORKBOOK",
        "real_submit_allowed":False,
        "data_conflict":False,"stale":False,
        "live_values_available":True,"price_source_status":"OK",
        "timestamp_timezone":"Asia/Tokyo",
        "observed_at_offset":"2026-10-16T09:19:59+09:00",
        "valid":100,
        "live_price_diagnostics":{
            "workbook_name":"Kioxia_MS2_RSS_Live_Signals.xlsx",
            "workbook_identity_verified":True,"source_mode":"MS2_RSS_WORKBOOK",
            "price_source_status":"OK","live_values_available":True,
            "data_conflict":False,"collector_count":1,"watcher_count":1,
            "source_timestamp":"09:19:58"
        },
        "all_targets":[
            {"ticker":f"{1000+i}.T","sheet_code":f"{1000+i}.T",
             "data":"LIVE","price":120,"vwap":115,"or_high":118,"or_low":110,
             "source_timestamp":"09:19:58"} for i in range(100)
        ],
    }

class BrainObserverTests(unittest.TestCase):
    def test_real_rss_shape_makes_nontrade_watch_not_market_auth(self):
        out=analyze(source(),now=NOW,file_modified_at=NOW-timedelta(seconds=1))
        self.assertEqual(out["state"],"OBSERVATION_ONLY")
        self.assertEqual(out["observed_rows"],100)
        self.assertEqual(out["watch_counts"]["OR15_ABOVE_VWAP_WATCH"],100)
        self.assertEqual(len(out["watch_observations"]),5)
        self.assertIsNone(out["last_market_data_at"])
        status=status_snapshot(out,now=NOW,pid=1234)
        self.assertFalse(status["source_authenticated"])
        self.assertFalse(status["signal_provenance_verified"])
        self.assertFalse(status["exchange_tick_date_verified"])
        self.assertFalse(status["cross_source_join_allowed"])
        self.assertFalse(status["promotion_eligible"])
        self.assertEqual(status["eligible_observed_n"],0)
        self.assertFalse(status["real_submit_allowed"])
        self.assertFalse(status["tested_expectancy_available"])
    def test_stale_forged_workbook_count_and_invalid_rows_block(self):
        for field,value in [("real_submit_allowed",True),("data_conflict",True),
                            ("live_values_available",False),("timestamp_timezone","UNKNOWN")]:
            s=source();s[field]=value
            out=analyze(s,now=NOW,file_modified_at=NOW)
            self.assertEqual(out["state"],"BLOCKED",field)
            self.assertEqual(out["watch_observations"],[])
        s=source();s["live_price_diagnostics"]["collector_count"]=2
        self.assertEqual(analyze(s,now=NOW,file_modified_at=NOW)["state"],"BLOCKED")
        s=source();s["all_targets"][1]["sheet_code"]="WRONG"
        self.assertEqual(analyze(s,now=NOW,file_modified_at=NOW)["state"],"BLOCKED")
        s=source();s["observed_at_offset"]="2026-10-16T09:19:59"
        self.assertEqual(analyze(s,now=NOW,file_modified_at=NOW)["state"],"BLOCKED")
        s=source();s["observed_at_offset"]="2026-10-16T09:19:59+00:00"
        self.assertEqual(analyze(s,now=NOW,file_modified_at=NOW)["state"],"BLOCKED")
        s=source()
        self.assertEqual(analyze(s,now=NOW+timedelta(minutes=3),file_modified_at=NOW)["state"],"BLOCKED")
    def test_incomplete_or15_never_watch(self):
        s=source()
        for r in s["all_targets"]:r["or_low"]=0
        out=analyze(s,now=NOW,file_modified_at=NOW)
        self.assertEqual(out["state"],"OBSERVATION_ONLY")
        self.assertEqual(out["watch_observations"],[])
    def test_missing_input_writes_private_blocked_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"ai_brain_observer_status_v1.json"
            out=run_once(Path(tmp)/"missing.json",path,now=NOW,pid=987)
            self.assertEqual(out["state"],"BLOCKED")
            self.assertTrue(path.is_file())
            persisted=json.loads(path.read_text())
            self.assertEqual(persisted["engine_pid"],987)
            self.assertFalse(persisted["source_authenticated"])
            self.assertFalse(persisted["real_submit_allowed"])
    def test_writes_valid_file_without_touching_original_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            live=Path(tmp)/"live_ms2.json"
            live.write_text(json.dumps(source()),encoding="utf8")
            import os
            os.utime(live,(NOW.timestamp(),NOW.timestamp()))
            original=live.read_bytes()
            out=run_once(live,Path(tmp)/"ai_brain_observer_status_v1.json",now=NOW,pid=987)
            self.assertEqual(out["state"],"OBSERVATION_ONLY")
            self.assertEqual(live.read_bytes(),original)
    def test_cannot_write_to_market_csv_or_misnamed_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            from scripts.ai_brain_observer import write_status
            with self.assertRaises(ValueError):
                write_status(Path(tmp)/"ticks.csv",{"real_submit_allowed":False})

if __name__=="__main__":
    unittest.main()
