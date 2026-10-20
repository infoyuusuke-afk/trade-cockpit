"""Synthetic-only v3 offline universe tests. No network/Excel/market data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "v3_universe_shadow.py"
spec = importlib.util.spec_from_file_location("v3_universe_shadow", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def row(code="TEST.T", roles=None, selected=True, **kw):
    return {
        "instrument_id": code,
        "instrument_type": "EQUITY",
        "roles": roles if roles is not None else ["B", "C"],
        "selected": selected,
        "observed_at": "2026-10-19T15:31:00+09:00",
        "available_at": "2026-10-19T15:32:00+09:00",
        "prior_day_trading_value_yen": 10_000_000_000,
        "turnover_session_date": "2026-10-19",
        "turnover_available_at": "2026-10-19T15:40:00+09:00",
        "spread_bps": 5.0,
        "bid_depth_yen": 5_000_000,
        "ask_depth_yen": 4_000_000,
        **kw,
    }


def payload(rows=None):
    return {
        "schema_version": "v3-universe-input-1",
        "selection_at": "2026-10-20T08:40:00+09:00",
        "input_source": "SYNTHETIC",
        "rights_verified": False,
        "session_id": "TEST_SESSION",
        "rows": rows if rows is not None else [row(), row("TST2.T", ["C"], False)],
    }


class V3UniverseShadow(unittest.TestCase):
    def test_overlap_and_prior_day_cap(self):
        s = mod.build_snapshot(payload())
        self.assertEqual(s["unique_instrument_count"], 2)
        self.assertEqual(s["role_assignment_counts"]["B"], 1)
        self.assertEqual(s["role_assignment_counts"]["C"], 2)
        self.assertEqual(s["rows"][0]["turnover_one_percent_cap_yen"], 100_000_000)
        self.assertIs(s["real_submit_allowed"], False)

    def test_no_lookahead_and_naive_time(self):
        r = row()
        r["available_at"] = "2026-10-20T16:00:00+09:00"
        with self.assertRaisesRegex(mod.ShadowReject, "LOOKAHEAD"):
            mod.build_snapshot(payload([r]))
        r["available_at"] = "2026-10-19T15:32:00"
        with self.assertRaisesRegex(mod.ShadowReject, "TIME_OFFSET_REQUIRED"):
            mod.build_snapshot(payload([r]))

    def test_missing_rights_rejected(self):
        d = payload()
        d["input_source"] = "MS2_LOCAL"
        with self.assertRaisesRegex(mod.ShadowReject, "RIGHTS_NOT_ATTESTED"):
            mod.build_snapshot(d)

    def test_duplicates_and_role_ceiling(self):
        with self.assertRaisesRegex(mod.ShadowReject, "DUPLICATE_INSTRUMENT"):
            mod.build_snapshot(payload([row(), row()]))
        with self.assertRaisesRegex(mod.ShadowReject, "ROLE_CAP_EXCEEDED_B"):
            mod.build_snapshot(payload([row("A%03d.T" % i, ["B"]) for i in range(9)]))

    def test_non_equity_cannot_enter_trading_candidate_lane(self):
        r = row()
        r["instrument_type"] = "INDEX"
        with self.assertRaisesRegex(mod.ShadowReject, "NON_EQUITY"):
            mod.build_snapshot(payload([r]))

    def test_unknown_turnover_not_zero_capacity(self):
        r = row()
        r["prior_day_trading_value_yen"] = None
        r["turnover_session_date"] = None
        r["turnover_available_at"] = None
        s = mod.build_snapshot(payload([r]))
        self.assertIsNone(s["rows"][0]["turnover_one_percent_cap_yen"])

    def test_forward_outcomes_have_separate_coverage_and_never_imply_ev(self):
        s = mod.build_snapshot(payload())
        obs = {"schema_version": "v3-universe-outcomes-1", "rows": [
            {"instrument_id": "TEST.T",
             "horizon_end_at": "2026-10-20T15:30:00+09:00",
             "available_at": "2026-10-20T16:00:00+09:00",
             "return_pct": 3.0}
        ]}
        out = mod.compare_outcomes(s, obs)
        self.assertEqual(out["comparison"]["selected"]["observed"], 1)
        self.assertEqual(out["comparison"]["unselected"]["missing"], 1)
        self.assertIsNone(out["comparison"]["unselected"]["mean_return_pct"])
        self.assertIsNone(out["net_expectancy"])
        obs["rows"][0]["horizon_end_at"] = "2026-10-20T08:30:00+09:00"
        with self.assertRaisesRegex(mod.ShadowReject, "OUTCOME_TIME_INVALID"):
            mod.compare_outcomes(s, obs)

    def test_turnover_point_in_time_rejects_future_or_unidentified_trading_value(self):
        for change, expected in (
            ({"turnover_session_date": "2026-10-20"}, "TURNOVER_MUST_PRECEDE"),
            ({"turnover_available_at": "2026-10-20T15:30:00+09:00"}, "TURNOVER_AVAILABLE"),
            ({"turnover_available_at": None}, "TIME_MISSING"),
            ({"turnover_session_date": None}, "TURNOVER_SESSION_DATE_REQUIRED"),
            ({"turnover_session_date": "2026-10-99"}, "TURNOVER_SESSION_DATE_INVALID"),
        ):
            x = row()
            x.update(change)
            with self.subTest(change=change), self.assertRaisesRegex(mod.ShadowReject, expected):
                mod.build_snapshot(payload([x]))

    def test_outcomes_must_use_one_common_horizon(self):
        snap = mod.build_snapshot(payload())
        obs = {"schema_version": "v3-universe-outcomes-1", "rows": [
            {"instrument_id": "TEST.T", "horizon_end_at": "2026-10-20T15:30:00+09:00",
             "available_at": "2026-10-20T15:31:00+09:00", "return_pct": 1},
            {"instrument_id": "TST2.T", "horizon_end_at": "2026-10-21T15:30:00+09:00",
             "available_at": "2026-10-21T15:31:00+09:00", "return_pct": -1}
        ]}
        with self.assertRaisesRegex(mod.ShadowReject, "OUTCOME_HORIZON_MISMATCH"):
            mod.compare_outcomes(snap, obs)
        obs["rows"][1]["horizon_end_at"] = "2026-10-20T15:30:00+09:00"
        obs["rows"][1]["available_at"] = "2026-10-20T15:31:00+09:00"
        got = mod.compare_outcomes(snap, obs)
        self.assertEqual(got["common_horizon_end_at"], "2026-10-20T15:30:00+09:00")

    def test_private_immutable_output_rejects_overwrite_and_repo_paths(self):
        s = mod.build_snapshot(payload())
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "record.json"
            digest = mod.write_private_snapshot(out, s)
            self.assertEqual(digest, s["snapshot_sha256"])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), s)
            with self.assertRaises(FileExistsError):
                mod.write_private_snapshot(out, s)
        with self.assertRaisesRegex(mod.ShadowReject, "GIT_REPOSITORY_OUTPUT_FORBIDDEN"):
            mod.write_private_snapshot(mod.ROOT / "never_write_this.json", s)


if __name__ == "__main__":
    unittest.main()
