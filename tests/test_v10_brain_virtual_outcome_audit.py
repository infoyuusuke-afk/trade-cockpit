"""Synthetic-only V10 virtual observation audit tests. No order capability."""
from datetime import datetime, timedelta, timezone
import copy
import json
import tempfile
from pathlib import Path
import unittest

from scripts.v10_brain_virtual_outcome_audit import audit, audit_local

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=JST)
BASE = "2026-10-19T09:00:00+09:00"


def event(seq, kind, minute):
    return {"record_class": "shadow_observation", "schema_version": "ai-shadow-supervisor-1",
            "seq": seq, "event_type": kind, "at": f"2026-10-19T09:{minute:02d}:00+09:00",
            "real_submit_allowed": False, "quantity": None,
            "pricing": "collector_published_price_not_fill_model"}


def fixture():
    a = event(1, "virtual_entry", 10)
    a.update(position_key="9999.T|LONG",ticker="9999.T",side="LONG",
             strategy="OR15_LONG",entry_price=100.0,stop_price=98.0,
             source_timestamp_at="2026-10-19T09:09:59+09:00",
             performance_bucket="open_unrealized_not_marked")
    b = event(2, "virtual_exit", 20)
    b.update(position_key="9999.T|LONG",ticker="9999.T",side="LONG",
             strategy="OR15_LONG",entry_price=100.0,exit_price=102.0,
             pnl_per_share_yen=2.0,r_multiple=1.0,related_entry_seq=1,
             performance_bucket="clean_strategy")
    return [a,b]


class VirtualOutcomeResearchAudit(unittest.TestCase):
    def test_clean_observation_reports_r_not_money_or_ev(self):
        output = audit(fixture(), now=NOW)
        self.assertEqual(output["state"], "RESEARCH_OBSERVATION_ONLY")
        self.assertEqual(output["virtual_closed_clean_n"], 1)
        self.assertEqual(output["strategy_statistics"][0]["virtual_mean_r"], 1)
        self.assertEqual(output["strategy_statistics"][0]["virtual_n"], 1)
        self.assertFalse(output["tested_expectancy_available"])
        self.assertFalse(output["broker_fills_verified"])
        self.assertFalse(output["real_submit_allowed"])
        for key in ("symbol", "entry_price", "pnl_yen", "trade_id", "account_number", "owner_name"):
            self.assertNotIn(key, str(output))

    def test_actual_ms2_japanese_strategy_is_accepted(self):
        events = fixture()
        events[0]["strategy"] = "OR15押し目"
        events[1]["strategy"] = "OR15押し目"
        result = audit(events, now=NOW)
        self.assertEqual(result["state"], "RESEARCH_OBSERVATION_ONLY")
        self.assertEqual(result["strategy_statistics"][0]["strategy_id"], "OR15押し目")

    def test_contaminated_not_counted_in_strategy(self):
        a = fixture();a[1]["performance_bucket"]="contaminated_by_data_outage"
        output = audit(a,now=NOW)
        self.assertEqual(output["virtual_closed_contaminated_n"],1)
        self.assertEqual(output["virtual_closed_clean_n"],0)
        self.assertEqual(output["strategy_statistics"],[])

    def test_open_never_counts_as_closed(self):
        out=audit(fixture()[:1],now=NOW)
        self.assertEqual(out["virtual_open_n"],1)
        self.assertEqual(out["virtual_closed_clean_n"],0)

    def test_orphan_exit_blocks_entire_ledger(self):
        self.assertEqual(audit(fixture()[1:],now=NOW)["state"],"BLOCKED")

    def test_gap_and_duplicate_seq_blocks(self):
        for n in (0,1,3,True):
            events=fixture();events[1]["seq"]=n
            self.assertEqual(audit(events,now=NOW)["state"],"BLOCKED")

    def test_real_flag_or_quantity_blocks(self):
        for key,value in (("real_submit_allowed",True),("real_submit_allowed",None),("quantity",100)):
            ev=fixture();ev[1][key]=value
            self.assertEqual(audit(ev,now=NOW)["state"],"BLOCKED")

    def test_missing_source_timestamp_blocks(self):
        ev=fixture();ev[0].pop("source_timestamp_at")
        self.assertEqual(audit(ev,now=NOW)["state"],"BLOCKED")

    def test_old_or_future_quote_at_blocks_research(self):
        for at in ("2026-10-18T09:09:59+09:00", "2026-10-19T09:10:01+09:00"):
            ev=fixture();ev[0]["source_timestamp_at"]=at
            self.assertEqual(audit(ev,now=NOW)["state"],"BLOCKED")

    def test_future_and_naive_timestamps_block(self):
        for at in ("2026-10-20T09:20:00+09:00","2026-10-19T09:20:00",None):
            ev=fixture();ev[1]["at"]=at
            self.assertEqual(audit(ev,now=NOW)["state"],"BLOCKED")

    def test_exit_reconciliation_catches_fabricated_pnl(self):
        for key,value in (("r_multiple",9.0),("pnl_per_share_yen",999.0),("entry_price",101.0)):
            ev=fixture();ev[1][key]=value
            self.assertEqual(audit(ev,now=NOW)["state"],"BLOCKED")

    def test_other_ticker_or_side_or_strategy_rejected(self):
        for key,value in (("ticker","1111.T"),("side","SHORT"),("strategy","OTHER")):
            ev=fixture();ev[1][key]=value
            self.assertEqual(audit(ev,now=NOW)["state"],"BLOCKED")

    def test_invalid_future_now_blocks(self):
        self.assertEqual(audit(fixture(),now=datetime(2026,10,19))["state"],"BLOCKED")

    def test_short_loss_and_pf(self):
        a=fixture();a[0].update(side="SHORT",position_key="9999.T|SHORT",stop_price=102.0)
        a[1].update(side="SHORT",position_key="9999.T|SHORT",exit_price=102.0,
                    pnl_per_share_yen=-2.0,r_multiple=-1.0)
        out=audit(a,now=NOW)
        self.assertEqual(out["state"],"RESEARCH_OBSERVATION_ONLY")
        self.assertEqual(out["strategy_statistics"][0]["virtual_mean_r"],-1)
        self.assertEqual(out["strategy_statistics"][0]["virtual_r_profit_factor"],0)

    def test_local_file_readonly_and_no_private_paths(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"ledger.jsonl"
            before="".join(json.dumps(v)+"\n" for v in fixture())
            p.write_text(before,encoding="utf-8")
            out=audit_local(p,now=NOW)
            self.assertEqual(out["state"],"RESEARCH_OBSERVATION_ONLY")
            self.assertEqual(p.read_text(encoding="utf-8"),before)
            self.assertNotIn(td,str(out))
            self.assertNotIn("9999.T",str(out))

    def test_invalid_json_fails_closed_without_leak(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"ledger.jsonl"
            p.write_text('{"secret":"synthetic"}\nBAD JSON\n',encoding="utf-8")
            out=audit_local(p,now=NOW)
            self.assertEqual(out["state"],"BLOCKED")
            self.assertNotIn("secret",str(out))
            self.assertNotIn(td,str(out))

    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as td:
            actual=Path(td)/"actual.jsonl"
            actual.write_text("{}\n",encoding="utf-8")
            link=Path(td)/"ledger.jsonl"
            try: link.symlink_to(actual)
            except (OSError,NotImplementedError): self.skipTest("symlink not available")
            self.assertEqual(audit_local(link,now=NOW)["reason"],"LEDGER_PATH_UNTRUSTED")

    def test_wrong_name_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"some_public_name.jsonl"
            p.write_text("{}\n",encoding="utf-8")
            self.assertEqual(audit_local(p,now=NOW)["state"],"BLOCKED")

if __name__=="__main__":unittest.main()
