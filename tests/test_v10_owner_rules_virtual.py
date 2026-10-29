"""OWNER 2026-10-27 「1回の損切り、1日の負けの上限3万円、6146・6920・285Aは仮想だけ、の決まりをブレインの仮想売買に入れて、
おれの実際の成績と毎日並べて」. Virtual only; synthetic rows."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import v10_positions_live as pos

ROOT = Path(__file__).resolve().parents[1]


def trade(ticker, fill_time, exit_time, ret, fill=1000.0, stop="990", status="CLOSED"):
    return {"ticker": ticker, "name": "n", "rule": "R1", "status": status, "fill_time": fill_time, "exit_time": exit_time,
            "fill_price": fill, "stop": stop, "return_pct": ret}


class OwnerRules(unittest.TestCase):
    def test_yen_is_100_shares_after_cost_and_watch_codes_are_apart(self):
        v = pos.owner_rules([trade("A.T", "09:20:00", "09:40:00", 1.0), trade("6920.T", "09:21:00", "09:30:00", -2.0),
                             trade("B.T", "09:22:00", None, None, status="OPEN")], "2026-10-27")
        self.assertEqual(v["counted"], {"n": 2, "closed": 1, "open": 1, "wins": 1, "losses": 0, "yen": 1000})
        self.assertEqual(v["virtual_only"]["yen"], -2000)
        self.assertEqual(v["virtual_only_codes"], ["6146", "6920", "285A"])
        self.assertEqual((v["shares"], v["daily_limit_yen"]), (100, -30000))

    def test_no_new_trade_after_the_closed_loss_reaches_30000(self):
        v = pos.owner_rules([trade("A.T", "09:20:00", "09:30:00", -3.5, fill=10000.0),   # -35,000 yen, closed 09:30
                             trade("B.T", "09:25:00", "09:50:00", 1.0),                    # filled before 09:30: counted
                             trade("C.T", "09:31:00", "09:45:00", 2.0)], "2026-10-27")     # after the limit: not counted
        self.assertEqual(v["counted"]["n"], 2)
        self.assertEqual(v["counted"]["yen"], -34000)
        self.assertEqual((v["skipped_after_limit"], v["limit_hit_at"]), (1, "09:31:00"))

    def test_a_trade_without_a_stop_is_not_counted(self):
        v = pos.owner_rules([trade("A.T", "09:20:00", "09:30:00", 1.0, stop="")], "2026-10-27")
        self.assertEqual((v["counted"]["n"], v["no_stop"]), (0, 1))

    def test_build_keeps_each_day_and_lists_the_history(self):
        tmp = Path(tempfile.mkdtemp(prefix="v10-owner-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        old = tmp / "records" / "2026-10-26"
        old.mkdir(parents=True)
        (old / pos.OWNER_RULES_FILE).write_text(json.dumps({"date": "2026-10-26", "counted": {"yen": 500}}), encoding="utf-8")
        (tmp / "records" / "2026-10-27").mkdir()
        from scripts import v10_signal_ev_table as ev
        from datetime import datetime, timedelta, timezone
        v = pos.build(tmp, now=datetime(2026, 10, 27, 15, 40, tzinfo=timezone(timedelta(hours=9))), ev=ev, rules=ev.RULES, state={})
        self.assertTrue((tmp / "records" / "2026-10-27" / pos.OWNER_RULES_FILE).is_file())
        self.assertEqual(v["owner_rules"]["history"][0]["date"], "2026-10-26")
        self.assertFalse(v["real_submit_allowed"])

    def test_brain_pick_carries_the_tally(self):
        src = (ROOT / "scripts" / "v10_brain_core.py").read_text(encoding="utf-8")
        self.assertIn('"owner_rules", "short_rebound")}', src)


class OwnerRulesScreen(unittest.TestCase):
    def test_control_glance_lists_ai_and_real_by_day(self):
        js = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        assert "AI（あなたのルール）と実口座　毎日の比べ" in js
        assert "const own=pos.owner_rules||null" in js
        assert 'localStorage.getItem("cockpitRealDailyV1")' in js and "記録なし" in js
        assert "0円とは扱いません" in js


if __name__ == "__main__":
    unittest.main()
