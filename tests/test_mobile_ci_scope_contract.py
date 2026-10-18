"""P0-33: Mobile Control CI runs the full current suite and excludes only the
pinned tests of V8/V9 scripts removed under D-003. Those stay in the manual
Legacy Full Suite Diagnostic.

This is a static/synthetic CI contract; no broker or Windows process is started.
"""
import importlib.util
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / ".github/workflows/mobile-control-tests.yml"
ARCHIVE = ROOT / ".github/workflows/legacy-full-suite-diagnostic.yml"
RUNNER = ROOT / "scripts/ci_mobile_current_suite.py"
LEGACY = ROOT / "scripts/ci_legacy_v8_v9_excluded.txt"

SAFETY_MODULES = (
    "test_mobile_approvals",
    "test_owner_approval_queue",
    "test_execution_contract",
    "test_execution_contract_boundary",
    "test_execution_permission",
    "test_autonomy_gate",
)
# Modules that hold tests of the removed V8/V9 scripts (some also hold current tests,
# which keep running because exclusion is per test ID).
LEGACY_MODULES = {
    "test_ai_cockpit_v8_controller_contract", "test_ai_shadow_supervisor",
    "test_collector_workbook_identity", "test_v9_alert_log", "test_v9_alert_payload",
    "test_v9_alert_sibling", "test_v9_cache_rest", "test_v9_cache_role",
    "test_v9_cache_tail", "test_v9_disabled_scope", "test_v9_excel_identity_probe",
    "test_v9_launch_record", "test_v9_local_cache", "test_v9_serious_error_diagnostic",
    "test_v9_serious_error_store", "test_v9_ui_voice_contract",
    "test_v9_workbook_recovery_registry",
}


def load_runner():
    spec = importlib.util.spec_from_file_location("ci_mobile_current_suite", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MobileCIScopeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mobile = MOBILE.read_text(encoding="utf-8")
        cls.archive = ARCHIVE.read_text(encoding="utf-8")
        cls.runner = load_runner()

    def test_mobile_ci_keeps_broad_triggers_and_runs_runner(self):
        for path in ('      - "scripts/**"', '      - "tests/**"',
                     '      - ".github/workflows/mobile-control-tests.yml"'):
            self.assertIn(path, self.mobile)
        self.assertIn("  pull_request:", self.mobile)
        self.assertIn("run: python scripts/ci_mobile_current_suite.py", self.mobile)
        self.assertIn("python -m unittest discover -s tests -p test_mobile_ci_scope_contract.py -v", self.mobile)
        for forbidden in ("continue-on-error", "|| true", "if: always()", "exit 0"):
            self.assertNotIn(forbidden, self.mobile)

    def test_legacy_list_is_pinned_and_never_names_v10(self):
        ids = sorted(self.runner.load_excluded())
        self.assertEqual(len(ids), 115, "legacy exclusions may only change deliberately")
        for test_id in ids:
            self.assertNotRegex(test_id.lower(), "v10")
            self.assertIn(test_id.split(".")[0], LEGACY_MODULES, test_id)
            self.assertEqual(len(test_id.split(".")), 3, test_id)
        for module in SAFETY_MODULES:
            self.assertFalse(any(i.startswith(module + ".") for i in ids), module)

    def test_runner_requires_safety_suites_and_fails_on_any_failure(self):
        self.assertEqual(tuple(self.runner.REQUIRED_MODULES), SAFETY_MODULES)
        for module in SAFETY_MODULES:
            self.assertTrue((ROOT / "tests" / (module + ".py")).is_file(), module)
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("result.wasSuccessful()", source)
        self.assertIn("LEGACY_EXCLUSION_NOT_PROVEN", source)
        self.assertIn("MOBILE_SAFETY_SUITE_MISSING", source)

    def test_pinned_exclusion_ids_are_all_or_none_across_branches(self):
        # main contains no legacy cases; the stacked V10 branch contains all.
        # A partially discovered inventory is a regression, not a PASS.
        validator = self.runner.verify_exclusion_ids
        ids = {"test_v9_fake.Legacy.test_old", "test_v8_fake.Legacy.test_old"}
        self.assertIsNone(validator(ids, set(ids)))
        self.assertIsNone(validator(ids, set()))
        with self.assertRaisesRegex(SystemExit, "LEGACY_LIST_PARTIALLY_DISCOVERED"):
            validator(ids, {"test_v9_fake.Legacy.test_old"})
        with self.assertRaisesRegex(SystemExit, "test_v8_fake"):
            validator(ids, {"test_v9_fake.Legacy.test_old"})

    def test_exclusion_requires_a_missing_v8_v9_script(self):
        runner = self.runner
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "downloads").mkdir()
            (root / "tests" / "test_fake.py").write_text(
                'X = "downloads" / "AI_COCKPIT_CONTROLLER_V9.ps1"\n', encoding="utf-8")
            saved = runner.ROOT, runner.TESTS
            runner.ROOT, runner.TESTS = root, root / "tests"
            try:
                self.assertEqual(runner.missing_legacy_refs("test_fake"),
                                 ["AI_COCKPIT_CONTROLLER_V9.ps1"])
                # A reintroduced V9 script means the test is no longer legacy (D-003).
                (root / "downloads" / "AI_COCKPIT_CONTROLLER_V9.ps1").write_text("", encoding="utf-8")
                self.assertEqual(runner.missing_legacy_refs("test_fake"), [])
            finally:
                runner.ROOT, runner.TESTS = saved

    def test_full_legacy_suite_is_retained_as_explicit_red_diagnostic(self):
        self.assertIn("name: Legacy Full Suite Diagnostic", self.archive)
        self.assertIn("  workflow_dispatch:", self.archive)
        self.assertNotIn("  pull_request:", self.archive)
        self.assertIn('python -m unittest discover -s tests -p "test_*.py" -v', self.archive)
        for forbidden in ("continue-on-error:", "|| true", "exit 0", "if: always()", "continueOnError"):
            self.assertNotIn(forbidden, self.archive)


if __name__ == "__main__":
    unittest.main()
