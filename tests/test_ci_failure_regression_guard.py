"""P0-417: prove regression visibility never turns known FAIL into PASS."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ci_failure_regression_guard import compare, report, signatures

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "tests" / "ci_known_failures_p0417.json"


class FailureBaselineTests(unittest.TestCase):
    def test_baseline_is_frozen_115_real_failures(self):
        d = json.loads(REFERENCE.read_text(encoding="utf-8"))
        self.assertEqual(d["schema"], "p0-417-known-ci-failures-v1")
        self.assertEqual(d["reference_run"], "39009738505")
        self.assertEqual(len(d["known_failures"]), 115)
        self.assertEqual(sum(s.startswith("FAIL ") for s in d["known_failures"]), 26)
        self.assertEqual(sum(s.startswith("ERROR ") for s in d["known_failures"]), 89)
        self.assertEqual(d["known_failures"], sorted(set(d["known_failures"])))

    def _fixture(self):
        t = tempfile.TemporaryDirectory(prefix="p0417-regression-")
        f = Path(t.name) / "baseline.json"
        f.write_text(json.dumps({
            "schema": "p0-417-known-ci-failures-v1",
            "known_failures": ["ERROR test_v9_old.Old.test_a", "FAIL test_v9_old.Old.test_b"]
        }), encoding="utf-8")
        return t, f

    def test_log_signature_deduplicates_final_unittest_failure_blocks(self):
        log = (
            "FAIL: test_b (test_v9_old.Old.test_b)\n"
            "ERROR: test_a (test_v9_old.Old.test_a)\n"
            "FAIL: test_b (test_v9_old.Old.test_b)\n"
        )
        self.assertEqual(signatures(log), [
            "ERROR test_v9_old.Old.test_a", "FAIL test_v9_old.Old.test_b"
        ])

    def test_unchanged_known_failure_is_not_called_a_pass(self):
        tmp, f = self._fixture()
        with tmp:
            log = ("ERROR: test_a (test_v9_old.Old.test_a)\n"
                   "FAIL: test_b (test_v9_old.Old.test_b)\n"
                   "FAILED (failures=1, errors=1)\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = report(log, f)
            self.assertEqual(rc, 0)  # only the delta is clean
            self.assertIn("P0_417_BASELINE_RESULT=UNCHANGED", output.getvalue())
            self.assertIn("P0_417_BASELINE_OBSERVED=2", output.getvalue())
            self.assertNotIn("P0_417_RESULT=PASS", output.getvalue())

    def test_new_failure_or_changed_type_is_blocked(self):
        tmp, f = self._fixture()
        with tmp:
            log = ("FAIL: test_a (test_v9_old.Old.test_a)\n"
                   "FAIL: test_b (test_v9_old.Old.test_b)\n")
            result = compare(log, f)
            self.assertTrue(result["regression"])
            self.assertEqual(result["new"], ["FAIL test_v9_old.Old.test_a"])
            self.assertEqual(result["absent"], ["ERROR test_v9_old.Old.test_a"])
            self.assertEqual(report(log, f), 1)

    def test_missing_baseline_is_blocked(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = report("", Path("/not-a-real-ci-baseline.json"))
        self.assertEqual(rc, 2)
        self.assertIn("P0_417_BASELINE_RESULT=BLOCKED_UNVERIFIED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
