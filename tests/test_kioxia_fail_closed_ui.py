import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
UPDATE = (ROOT / "scripts" / "update.py").read_text(encoding="utf-8")


class KioxiaFailClosedUiContractTests(unittest.TestCase):
    def test_local_collector_connectivity_is_explicit(self):
        self.assertIn("d.collector_connected=true", UPDATE)
        self.assertIn("d.collector_connected=false", UPDATE)
        self.assertIn("collectorDown=d.collector_connected===false", UPDATE)

    def test_collector_stop_and_stale_block_live_use(self):
        self.assertIn('"KIOXIA COLLECTOR STOPPED"', UPDATE)
        self.assertIn('"KIOXIA STALE DATA"', UPDATE)
        self.assertIn('"COLLECTOR_STOPPED","キオクシア、コレクター停止。', UPDATE)
        self.assertIn('"STALE_DATA","キオクシア、データ鮮度切れ。', UPDATE)
        self.assertIn("stale=freshnessStale||collectorDown", UPDATE)

    def test_fail_closed_priority_and_recovery_are_explicit(self):
        self.assertIn("priority={DATA_CONFLICT:1,STALE_DATA:2,COLLECTOR_STOPPED:3}", UPDATE)
        self.assertIn('card.classList.remove("live-invalid")', UPDATE)
        self.assertIn('card.querySelector(".live-state-proof")?.remove()', UPDATE)
        self.assertIn('sessionStorage.removeItem("kioFailClosedVoice")', UPDATE)

    def test_data_conflict_uses_shared_fail_closed_path(self):
        self.assertIn('setKioFailClosed("DATA_CONFLICT","KIOXIA DATA CONFLICT"', UPDATE)
        self.assertIn('DATA_CONFLICT|${mp}|${wp}', UPDATE)
        self.assertNotIn("kioDataConflictVoice", UPDATE)


if __name__ == "__main__":
    unittest.main()
