"""Synthetic only. Verifies no lookahead, no real broker, no paid LLM usage."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from hashlib import sha256
import io
import json
import unittest
from datetime import timezone

from scripts.zero_token_strategy_lab import (
    BAR_COLS, ResearchBlocked, _metric, _day_block_lower,
    analyze, load_bars_bytes, replay_one_day, variants,
)

JST=timezone(timedelta(hours=9))
SHA="0"*64


def synthetic_rows(*, symbol="285A", date="2026-10-19",
                   days=1, n=100, source="SYNTHETIC_TEST_ONLY",
                   breach=False, signal_delayed=False, stop_and_target=False):
    """Only 9am artificial bar data, NOT actual or historical market returns."""
    base=datetime.fromisoformat(date+"T09:00:15+09:00")
    result=[]
    for i in range(n):
        ts=base+timedelta(seconds=15*i)
        op=100.0; close=100.0; hi=100.03; lo=99.97
        if i==20 and breach:
            close=100.5; hi=100.6; lo=99.99
        if i>=21 and breach:
            op=100.5; close=100.53; hi=100.54; lo=100.48
        if i==22 and breach:
            hi=101.1
        if i==22 and breach and stop_and_target:
            lo=99.8; hi=101.2
        available=ts+timedelta(seconds=5) if i==20 and signal_delayed else ts
        result.append({"symbol":symbol,"time":ts.isoformat(),
            "available_at":available.isoformat(),"open":op,"high":hi,
            "low":lo,"close":close,"volume":1000,"source":source,
            "quality":"CONFIRMED"})
    return result


def encode(rows):
    output=io.StringIO(newline="")
    writer=csv.DictWriter(output,fieldnames=BAR_COLS,lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def long_variant():
    return next(x for x in variants() if x["or_bars"]==20 and
        x["side"]=="LONG" and x["setup"]=="BREAK" and
        x["stop_bps"]==30 and x["reward_r"]==1.5 and x["hold_bars"]==40)


class ZeroTokenLabTests(unittest.TestCase):
    def parsed(self, **kw):
        return load_bars_bytes(encode(synthetic_rows(**kw)))[0]

    def test_grid_is_bounded_64(self):
        all_=variants()
        self.assertEqual(len(all_),64)
        self.assertEqual(len({v["id"] for v in all_}),64)

    def test_opening_breakout_uses_delayed_second_bar_open(self):
        bars=self.parsed(breach=True)
        x=replay_one_day(bars,long_variant(),cost_bps=18.)
        self.assertIsNotNone(x)
        self.assertEqual(x["decision_at"],bars[20]["time"].isoformat())
        self.assertEqual(x["entry_bar_end"],bars[22]["time"].isoformat())
        self.assertEqual(x["exit_reason"],"TARGET")
        self.assertGreater(x["net_bps"],0)
        self.assertEqual(x["cost_bps"],18)
        self.assertIs(x["real_submit_allowed"],False)

    def test_five_second_source_lag_uses_second_next_bar_open(self):
        bars=self.parsed(breach=True,signal_delayed=True)
        result=replay_one_day(bars,long_variant(),cost_bps=18)
        self.assertIsNotNone(result)
        self.assertEqual(result["entry_bar_end"],bars[22]["time"].isoformat())
        self.assertFalse(result["real_submit_allowed"])

    def test_sixteen_second_signal_lag_cannot_fill_past_entry_open(self):
        bars=self.parsed(breach=True)
        bars[20]["available_at"]=bars[20]["time"]+timedelta(seconds=16)
        self.assertIsNone(replay_one_day(bars,long_variant(),cost_bps=18))

    def test_delayed_earlier_vwap_bar_not_seen_at_prev_decision(self):
        bars=self.parsed(breach=True)
        # The previous VWAP bar was available only after the prior
        # decision time. A later complete file must not backdate it.
        bars[10]["available_at"]=bars[10]["time"]+timedelta(seconds=120)
        self.assertIsNone(replay_one_day(bars,long_variant(),cost_bps=18))

    def test_gap_prior_to_later_breakout_cannot_be_backfilled(self):
        bars=self.parsed(breach=True)
        # Shift the only signal from bar 20 to bar 25, then erase bar 23.
        bars[20]["close"]=100
        bars[20]["high"]=100.03
        for i in range(21,25):
            bars[i]["open"]=100
            bars[i]["close"]=100
            bars[i]["high"]=100.03
            bars[i]["low"]=99.97
        bars[25]["open"]=100
        bars[25]["close"]=100.5
        bars[25]["high"]=100.6
        bars[25]["low"]=99.99
        bars.pop(23)
        self.assertIsNone(replay_one_day(bars,long_variant(),cost_bps=18))

    def test_both_stop_target_same_bar_stop_first(self):
        bars=self.parsed(breach=True,stop_and_target=True)
        trade=replay_one_day(bars,long_variant(),cost_bps=18)
        self.assertEqual(trade["exit_reason"],"STOP_FIRST_IF_AMBIGUOUS")
        self.assertLess(trade["net_bps"],0)

    def test_missing_future_bar_blocks_trade_instead_of_interpolating(self):
        bars=self.parsed(breach=True)
        # Removing a bar before the target simulates a stale/missing feed.
        bars.pop(22)
        self.assertIsNone(replay_one_day(bars,long_variant(),cost_bps=18))

    def test_missing_opening_bar_blocks_setup(self):
        bars=self.parsed(breach=True)
        bars.pop(4)
        self.assertIsNone(replay_one_day(bars,long_variant(),cost_bps=18))

    def test_no_breakout_no_trade(self):
        self.assertIsNone(replay_one_day(self.parsed(),long_variant(),cost_bps=18))

    def test_late_availability_is_never_repaired(self):
        rows=synthetic_rows()
        t=datetime.fromisoformat(rows[0]["time"])
        rows[0]["available_at"]=(t+timedelta(seconds=121)).isoformat()
        with self.assertRaisesRegex(ResearchBlocked,"BAR_AVAILABLE_AT_INVALID"):
            load_bars_bytes(encode(rows))

    def test_duplicate_suffix_alias_denied(self):
        rows=synthetic_rows(n=1)
        dup=dict(rows[0]);dup["symbol"]="285A.T"
        with self.assertRaisesRegex(ResearchBlocked,"DUPLICATE_SYMBOL_TIME"):
            load_bars_bytes(encode([rows[0],dup]))

    def test_json_utf8_and_nan_denied(self):
        rows=synthetic_rows(n=1);rows[0]["close"]=float("nan")
        with self.assertRaisesRegex(ResearchBlocked,"NUMERIC_INVALID"):
            load_bars_bytes(encode(rows))

    def test_contradictory_ohlc_denied(self):
        rows=synthetic_rows(n=1);rows[0]["low"]=101
        with self.assertRaisesRegex(ResearchBlocked,"OHLC_CONTRADICTION"):
            load_bars_bytes(encode(rows))

    def test_source_mixing_denied(self):
        rows=synthetic_rows(n=2);rows[1]["source"]="MS2_RSS_15S_CONFIRMED"
        with self.assertRaisesRegex(ResearchBlocked,"MIXED_SYNTHETIC_REAL_INPUT"):
            load_bars_bytes(encode(rows))

    def test_unknown_quality_denied(self):
        rows=synthetic_rows(n=1);rows[0]["quality"]="UNKNOWN"
        with self.assertRaisesRegex(ResearchBlocked,"SOURCE_OR_QUALITY_NOT_CONFIRMED"):
            load_bars_bytes(encode(rows))

    def test_naive_timestamp_denied(self):
        rows=synthetic_rows(n=1);rows[0]["time"]="2026-10-19T09:00:15"
        with self.assertRaisesRegex(ResearchBlocked,"TIMESTAMP_NAIVE"):
            load_bars_bytes(encode(rows))

    def test_weekend_denied(self):
        with self.assertRaisesRegex(ResearchBlocked,"BAR_SESSION_OR_GRANULARITY_INVALID"):
            load_bars_bytes(encode(synthetic_rows(date="2026-10-18",n=1)))

    def test_lunch_time_denied(self):
        rows=synthetic_rows(n=1)
        rows[0]["time"]="2026-10-19T12:00:00+09:00"
        rows[0]["available_at"]=rows[0]["time"]
        with self.assertRaisesRegex(ResearchBlocked,"BAR_SESSION_OR_GRANULARITY_INVALID"):
            load_bars_bytes(encode(rows))

    def test_not_enough_history_is_explicit(self):
        bars=self.parsed()
        out=analyze(bars,input_sha256=SHA)
        self.assertEqual(out["status"],"INSUFFICIENT_HISTORY")
        self.assertIsNone(out["best_research_candidate"])
        self.assertFalse(out["promotion_eligible"])
        self.assertFalse(out["real_submit_allowed"])
        self.assertFalse(out["shadow_order_created"])
        self.assertEqual(out["llm_api_tokens_used"],0)

    def test_cost_below_10_bps_denied(self):
        with self.assertRaisesRegex(ResearchBlocked,"ROUND_TRIP_COST_UNREALISTIC"):
            analyze(self.parsed(),input_sha256=SHA,base_cost_bps=1)

    def test_data_mixing_blocks_fake_provenance(self):
        with self.assertRaisesRegex(ResearchBlocked,"INPUT_FINGERPRINT_INVALID"):
            analyze(self.parsed(),input_sha256="unknown")

    def test_net_metric_subtracts_cost_once(self):
        row={"date":"2026-10-19","gross_bps":40,"cost_bps":18,"net_bps":22}
        a=_metric([row])
        self.assertEqual(a["mean_net_bps"],22)
        stressed=_metric([row],cost_override=36)
        self.assertEqual(stressed["mean_net_bps"],4)

    def test_day_block_bootstrap_ignores_insufficient_days(self):
        same_day=[{"date":"2026-10-19","net_bps":100}]*30
        self.assertIsNone(_day_block_lower(same_day,candidates=64,seed="test"))

    def test_historical_input_is_never_made_up(self):
        # Even 90 different session days of constant synthetic returns
        # must not be promoted as positive trading evidence.
        bars=[]
        dt=datetime(2026,1,5,tzinfo=JST)
        days=0
        while days<90:
            if dt.weekday()<5:
                rows=synthetic_rows(date=dt.date().isoformat(),n=80)
                bs,_=load_bars_bytes(encode(rows))
                bars.extend(bs)
                days+=1
            dt+=timedelta(days=1)
        out=analyze(bars,input_sha256=SHA)
        self.assertEqual(out["observed_days"],90)
        self.assertEqual(out["status"],"NO_VALIDATED_EDGE")
        self.assertFalse(out["promotion_eligible"])
        self.assertFalse(out["real_submit_allowed"])


if __name__=="__main__":
    unittest.main()
