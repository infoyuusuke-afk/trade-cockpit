"""P0-33: Mobile Control CI must test the owner-approval/order gates
without silently absorbing all archived V8/V9 diagnostic suites.

This is a static CI contract; no broker or Windows process is started.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / ".github/workflows/mobile-control-tests.yml"
ARCHIVE = ROOT / ".github/workflows/legacy-full-suite-diagnostic.yml"

SOURCES = (
    "scripts/build_mobile_approvals.py",
    "scripts/owner_approval_queue.py",
    "scripts/execution_contract.py",
    "scripts/execution_permission.py",
    "scripts/autonomy_gate.py",
)
TESTS = (
    "test_mobile_approvals.py",
    "test_owner_approval_queue.py",
    "test_execution_contract.py",
    "test_execution_contract_boundary.py",
    "test_execution_permission.py",
    "test_autonomy_gate.py",
)


class MobileCIScopeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mobile = MOBILE.read_text(encoding="utf-8")
        cls.archive = ARCHIVE.read_text(encoding="utf-8")

    def test_mobile_triggers_include_each_approval_and_execution_module(self):
        for source in SOURCES:
            self.assertIn(f'      - "{source}"', self.mobile)
            self.assertTrue((ROOT / source).is_file(), source)
        for test in TESTS:
            self.assertIn(f'      - "tests/{test}"', self.mobile)
            self.assertTrue((ROOT / "tests" / test).is_file(), test)
        self.assertIn('      - "tests/test_mobile_ci_scope_contract.py"', self.mobile)
        self.assertIn('      - "data/ev_calibration.json"', self.mobile)
        self.assertIn('      - "data/strategy_registry.json"', self.mobile)

    def test_execution_safety_suite_always_runs_and_fails_closed(self):
        self.assertIn("set -euo pipefail", self.mobile)
        for test in TESTS:
            self.assertIn("            " + test, self.mobile)
            # The tests are run via unittest discover, no filter disabling assertions.
        self.assertIn('python -m unittest discover -s tests -p "$suite" -v', self.mobile)
        self.assertIn("python -m unittest discover -s tests -p test_mobile_ci_scope_contract.py -v", self.mobile)
        for forbidden in ("continue-on-error:", "|| true", "pytest -k not", "--exclude"):
            self.assertNotIn(forbidden, self.mobile)

    def test_no_broad_trigger_or_unrelated_legacy_execution(self):
        for broad in ('      - "tests/**"', '      - "scripts/**"', 'test_*.py', 'test_v9_', 'test_ai_cockpit_v8'):
            self.assertNotIn(broad, self.mobile)
        self.assertIn("  pull_request:", self.mobile)
        self.assertIn("  workflow_dispatch:", self.mobile)

    def test_full_legacy_suite_is_retained_as_explicit_red_diagnostic(self):
        self.assertIn("name: Legacy Full Suite Diagnostic", self.archive)
        self.assertIn("  workflow_dispatch:", self.archive)
        self.assertNotIn("  pull_request:", self.archive)
        self.assertIn('python -m unittest discover -s tests -p "test_*.py" -v', self.archive)
        for forbidden in ("continue-on-error:", "|| true", "exit 0", "if: always()", "continueOnError"):
            self.assertNotIn(forbidden, self.archive)


if __name__ == "__main__":
    unittest.main()
