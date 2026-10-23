"""Virtual holdings (OWNER 2026-10-23): rule positions replayed on today's ticks, the 15:25
carry-over held until the next day's 15:30, swing/value reported as unknown. Synthetic only."""
from datetime import datetime, timedelta, timezone
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import v10_positions_live as pos
from scripts import v10_signal_ev_table as ev
from tests.test_v10_brain_core import SHADOW, TABLE, live, target

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))


def at(day, hm):
    h, m = map(int, hm.split(":"))
    return datetime(2026, 10, day, h, m, tzinfo=JST)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


class Positions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-pos-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        rec = self.tmp / "records"
        # rule ② short at 09:16, entry 1171.5, target 1137, stop 1194.5, longest hold 60 min
        write_csv(rec / "2026-10-23" / pos.RULE_SIGNALS_FILE,
                  ["captured_at", "ticker", "name", "signal", "strategy", "signal_bar", "rule", "entry", "target", "stop"],
                  [{"captured_at": "2026-10-23 09:16:34", "ticker": "A.T", "name": "名A", "signal": "空売りサイン",
                    "strategy": "OR15戻り", "signal_bar": "2026-10-23 09:15", "rule": "R2", "entry": "1171.5",
                    "target": "1137.0", "stop": "1194.5"}])
        self.ticks = rec / "2026-10-23" / pos.TICKS_FILE
        write_csv(self.ticks, ["captured_at", "ticker", "name", "exchange_time", "price"],
                  [{"captured_at": "x", "ticker": "A.T", "name": "n", "exchange_time": "09:17:05", "price": "1170"},
                   {"captured_at": "x", "ticker": "B.T", "name": "n", "exchange_time": "09:17:06", "price": "999"}])
        write_csv(rec / "2026-10-22" / pos.OVERNIGHT_FILE, ["finalized_at", "rank", "ticker", "name", "hold_signal",
                                                             "reference_price_1525"],
                  [{"finalized_at": "2026-10-22 15:25:02", "rank": "1", "ticker": "9434.T", "name": "ソフトバンク（9434）",
                    "hold_signal": "持ち越しショート確定", "reference_price_1525": "245.5"}])

    def test_open_then_stopped_and_carry_over(self):
        state = {}
        v = pos.build(self.tmp, now=at(23, "09:20"), ev=ev, rules=ev.RULES, state=state)
        self.assertEqual(v["rule_positions"][0]["status"], "OPEN")         # filled at 1170, no stop/target yet
        self.assertEqual(v["counts"], {"rule_open": 1, "overnight": 1})
        self.assertEqual(v["overnight"][0]["side"], "SHORT")
        self.assertEqual((v["swing"], v["value"], v["real_submit_allowed"]), (None, None, False))
        with open(self.ticks, "a", newline="", encoding="utf-8") as f:   # appended ticks are read incrementally
            f.write("x,A.T,n,09:18:01,1199.5\n")
        v = pos.build(self.tmp, now=at(23, "09:21"), ev=ev, rules=ev.RULES, state=state)
        p = v["rule_positions"][0]
        self.assertEqual((p["status"], p["exit"], p["exit_price"]), ("CLOSED", "STOP", 1199.5))
        self.assertEqual(set(state["ticks_state"]["ticks"]), {"A.T"})       # only issues with a signal today
        self.assertEqual(json.loads((self.tmp / pos.OUT_FILE).read_text("utf-8"))["counts"]["rule_open"], 0)

    def test_time_exit_after_the_longest_hold_and_carry_over_until_1530(self):
        v = pos.build(self.tmp, now=at(23, "10:30"), ev=ev, rules=ev.RULES, state={})
        self.assertEqual((v["rule_positions"][0]["status"], v["rule_positions"][0]["exit"]), ("CLOSED", "TIME_EXIT"))
        self.assertEqual(len(pos.build(self.tmp, now=at(23, "15:31"), ev=ev, rules=ev.RULES, state={})["overnight"]), 0)

    def test_friday_holds_stay_over_the_weekend(self):
        # OWNER 2026-10-24 「持ち越しているはず」: Friday's 15:25 holds are held on Saturday and Sunday and scored
        # at Monday's close
        write_csv(self.tmp / "records" / "2026-10-23" / pos.OVERNIGHT_FILE,
                  ["finalized_at", "rank", "ticker", "name", "hold_signal", "reference_price_1525"],
                  [{"finalized_at": "2026-10-23 15:25:00", "rank": "1", "ticker": "5713.T", "name": "住友金属鉱山（5713）",
                    "hold_signal": "持ち越しロング確定", "reference_price_1525": "7981"}])
        for day, hm in ((24, "03:40"), (24, "16:00"), (25, "20:00"), (26, "10:00")):
            got = pos.build(self.tmp, now=at(day, hm), ev=ev, rules=ev.RULES, state={})["overnight"]
            self.assertEqual([(x["ticker"], x["valid_until"]) for x in got], [("5713.T", "2026-10-26 15:30")], (day, hm))
        self.assertEqual(pos.build(self.tmp, now=at(26, "15:31"), ev=ev, rules=ev.RULES, state={})["overnight"], [])

    def test_waiting_inside_the_fill_window(self):
        self.ticks.write_text("captured_at,ticker,name,exchange_time,price\nx,A.T,n,09:17:05,1180\n", encoding="utf-8-sig")
        self.assertEqual(pos.build(self.tmp, now=at(23, "09:20"), ev=ev, rules=ev.RULES, state={})["rule_positions"][0]["status"],
                         "WAITING")
        self.assertEqual(pos.build(self.tmp, now=at(23, "09:50"), ev=ev, rules=ev.RULES, state={})["rule_positions"][0]["status"],
                         "NOT_FILLED")

    def test_observer_pins_and_passes_positions_to_the_brain(self):
        spec = importlib.util.spec_from_file_location("obs_pos_under_test", ROOT / "scripts" / "ai_brain_observer.py")
        obs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obs)
        name, pin = obs.POSITIONS_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        (self.tmp / "signal_ev_table_v1.json").write_text(json.dumps(TABLE), encoding="utf-8")
        (self.tmp / "rule_shadow_v1.json").write_text(json.dumps(SHADOW, ensure_ascii=False), encoding="utf-8")
        path = self.tmp / "live_ms2.json"
        path.write_text(json.dumps(live([target("A.T")], at="2026-10-23 09:19:55"), ensure_ascii=False), encoding="utf-8")
        obs.brain_core_pass({}, path, now=at(23, "09:20").astimezone(timezone.utc))
        view = json.loads((self.tmp / "brain_pick_v1.json").read_text("utf-8"))
        self.assertEqual(view["positions"]["counts"], {"rule_open": 1, "overnight": 1})
        self.assertFalse(view["real_submit_allowed"])


if __name__ == "__main__":
    unittest.main()
