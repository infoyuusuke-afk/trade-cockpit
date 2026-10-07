import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.ai_shadow_supervisor import attach_candidate_sidecar


class CandidateSidecarTests(unittest.TestCase):
    def _payload(self):
        return {
            "all_targets": [{
                "ticker": "285A.T",
                "signal": "買いサイン",
                "strategy": "OR15",
                "price": 1000.0,
                "entry_price": 1000.0,
                "stop_price": 990.0,
                "data": "LIVE",
            }]
        }

    def test_fresh_valid_sidecar_only_adds_lineage(self):
        tz = timezone(timedelta(hours=9))
        now = datetime(2026, 10, 7, 9, 1, tzinfo=tz)
        with tempfile.TemporaryDirectory() as td:
            live_path = Path(td) / "live_ms2.json"
            sidecar = {
                "candidate_id": "prod-abc",
                "symbol": "285A.T",
                "side": "LONG",
                "generated_at": now.isoformat(),
                "execution_authority": False,
                "real_submit_allowed": False,
            }
            (Path(td) / "brain_candidate_live.json").write_text(json.dumps(sidecar), encoding="utf-8")
            original = self._payload()
            enriched = attach_candidate_sidecar(original, live_path=live_path, now=now)
            self.assertNotIn("candidate_id", original["all_targets"][0])
            self.assertEqual(enriched["all_targets"][0]["candidate_id"], "prod-abc")
            self.assertEqual(enriched["all_targets"][0]["signal"], "買いサイン")
            self.assertEqual(enriched["all_targets"][0]["price"], 1000.0)

    def test_stale_or_no_trade_sidecar_is_ignored(self):
        tz = timezone(timedelta(hours=9))
        now = datetime(2026, 10, 7, 9, 1, tzinfo=tz)
        with tempfile.TemporaryDirectory() as td:
            live_path = Path(td) / "live_ms2.json"
            sidecar = {
                "candidate_id": "watch-abc",
                "symbol": "285A.T",
                "side": "NO-TRADE",
                "generated_at": (now - timedelta(seconds=120)).isoformat(),
                "execution_authority": False,
                "real_submit_allowed": False,
            }
            (Path(td) / "brain_candidate_live.json").write_text(json.dumps(sidecar), encoding="utf-8")
            enriched = attach_candidate_sidecar(self._payload(), live_path=live_path, now=now)
            self.assertNotIn("candidate_id", enriched["all_targets"][0])


if __name__ == "__main__":
    unittest.main()
