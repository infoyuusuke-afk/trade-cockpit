"""Fail-closed UI evidence tests; synthetic, no MS2 or order connectivity."""
import json
import pathlib
import re
import shutil
import subprocess
import unittest

HTML = pathlib.Path(__file__).resolve().parents[1] / "index.html"
START = "// V10_UI_EVIDENCE_HELPERS_START"
END = "// V10_UI_EVIDENCE_HELPERS_END"


class V10UiEvidenceRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HTML.read_text(encoding="utf-8")
        cls.helpers = cls.source.split(START, 1)[1].split(END, 1)[0]

    def evaluate(self, js_expression):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is not present; static invariants still verified")
        program = self.helpers + "\nprocess.stdout.write(JSON.stringify(" + js_expression + "));"
        result = subprocess.run(
            [node, "-e", program], text=True, capture_output=True, check=True,
            timeout=15,
        )
        return json.loads(result.stdout)

    def test_controlled_layout_and_colors_remain_unchanged(self):
        actual = re.findall(r'<button class="cockpit-tab(?: active)?" data-tab="([^"]+)"', self.source)
        self.assertEqual(actual, [
            "control", "brain", "scalp", "event-hot", "ms2-live",
            "overnight", "swing", "value", "kioxia-calendar", "events",
            "strong-yen", "us-smr", "investor-regime", "market",
            "correlation", "wick", "expansion", "accumulation",
            "policy", "weekly",
        ])

    def test_no_fabricated_brain_gateway_or_live_label(self):
        self.assertNotIn('["BRAIN GATEWAY","28584 ONLINE"]', self.source)
        self.assertNotIn('["BRAIN STATE",ok?"LIVE":"FAIL-CLOSED"]', self.source)
        self.assertIn('["BRAIN OBSERVER",proof.observer]', self.source)
        self.assertIn('["BRAIN STATE",proof.brainState]', self.source)

    def test_brain_missing_or_unknown_conflict_blocks(self):
        rows = self.evaluate("""[
          cockpitBrainEvidence({},{}),
          cockpitBrainEvidence({brain_observer_state:'BRAIN_OBSERVING_PUBLICATION_ONLY'}, {real_submit_allowed:false}),
          cockpitBrainEvidence({brain_observer_state:'BRAIN_OBSERVING_PUBLICATION_ONLY',data_conflict:false}, {real_submit_allowed:true}),
          cockpitBrainEvidence({brain_observer_state:'INVALID',data_conflict:false}, {real_submit_allowed:false})
        ]""")
        self.assertTrue(all(x["brainState"] == "FAIL-CLOSED" for x in rows))
        self.assertEqual(rows[0]["observer"], "UNKNOWN")
        self.assertEqual(rows[1]["dataConflict"], "UNKNOWN")

    def test_observer_only_valid_explicit_negative_data_conflict(self):
        x = self.evaluate("""cockpitBrainEvidence({
          brain_observer_state:'BRAIN_OBSERVING_PUBLICATION_ONLY',data_conflict:false
        },{real_submit_allowed:false})""")
        self.assertEqual(x, {
            "observer": "BRAIN_OBSERVING_PUBLICATION_ONLY",
            "dataConflict": "FALSE",
            "brainState": "OBSERVATION_ONLY",
        })
        self.assertNotEqual(x["brainState"], "LIVE")

    def test_legacy_jst_snapshot_same_day_but_old_is_stale(self):
        x = self.evaluate("""cockpitSnapshotHealth(
           '2026-10-20 09:00:00 JST',Date.UTC(2026,9,20,4,35,0))""")
        self.assertEqual(x["cls"], "status-error")
        self.assertIn("鮮度切れ", x["title"])

    def test_recent_snapshot_is_warning_not_live_verified(self):
        values = self.evaluate("""[
          cockpitSnapshotHealth('2026-10-20 13:30:00 JST',Date.UTC(2026,9,20,4,35)),
          cockpitSnapshotHealth('2026-10-20T13:30:00+09:00',Date.UTC(2026,9,20,4,35))
        ]""")
        self.assertEqual([x["cls"] for x in values], ["status-warn","status-warn"])
        self.assertTrue(all("LIVE" not in x["title"] or "未検証" in x["title"] for x in values))

    def test_missing_unqualified_future_or_malformed_timestamp_block(self):
        values = self.evaluate("""[
          cockpitSnapshotHealth(null,Date.UTC(2026,9,20,4,35)),
          cockpitSnapshotHealth('2026-10-20 13:30:00',Date.UTC(2026,9,20,4,35)),
          cockpitSnapshotHealth('nonsense',Date.UTC(2026,9,20,4,35)),
          cockpitSnapshotHealth('2026-10-20 14:30:00 JST',Date.UTC(2026,9,20,4,35))
        ]""")
        self.assertTrue(all(x["cls"] == "status-error" for x in values))

    def test_source_errors_also_mark_status_error(self):
        self.assertIn('badge.title="分析スナップショット取得失敗・LIVE未検証"', self.source)
        self.assertNotIn('title="正常稼働中／最終更新 "', self.source)


if __name__ == "__main__":
    unittest.main()
