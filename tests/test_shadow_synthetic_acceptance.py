import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("shadow_synthetic_acceptance", ROOT / "scripts" / "shadow_synthetic_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


acc = _load()


class SyntheticAcceptanceTests(unittest.TestCase):
    def test_replay_passes_without_becoming_a_live_pass(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            result = acc.run_synthetic_acceptance(Path(temp))
        self.assertTrue(result["ok"])
        self.assertEqual(result["live_roundtrip"], "NOT_RUN/SYNTHETIC_LEDGER")
        text = acc.format_report(result)
        self.assertIn("SYNTHETIC_ACCEPTANCE=PASS", text)
        self.assertIn("LIVE_ROUNDTRIP=NOT_RUN/SYNTHETIC_LEDGER", text)
        self.assertNotIn("LIVE_ROUNDTRIP=PASS", text)
        self.assertFalse(result["real_submit_allowed"])

    def test_runner_does_not_submit(self):
        text = (ROOT / "scripts" / "shadow_synthetic_acceptance.py").read_text(encoding="utf-8")
        self.assertNotIn("submit_shadow_order", text)
        self.assertNotIn("shadow_execution", text)
        self.assertIn('acceptance_class="synthetic"', text)
