"""P0-417: synthetic proof that full-suite execution is never filtered."""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci_attributed_unittest as target


class AttributionTests(unittest.TestCase):
    def test_classification_covers_legacy_and_other(self):
        for name in (
            "test_v9_cache_rest.CacheRestTests.test_refuses",
            "test_v8_boot.Boot.test_one",
            "test_ai_cockpit_v8_controller_contract.Contract.test_foo",
            "test_ai_cockpit_v9_controller_contract.Contract.test_foo",
            "unittest.loader._FailedTest.test_v9_deleted_script",
        ):
            self.assertEqual(target.classify(name), "LEGACY_V8_V9", name)
        for name in ("test_mobile_foo.Check.test_one",
                     "test_v10_owner_state_metadata_v2.Check.test_foo",
                     "unittest.loader._FailedTest.test_unknown"):
            self.assertEqual(target.classify(name), "CURRENT_OTHER", name)

    def test_parses_final_unittest_failure_lines(self):
        output = ("FAIL: test_missing (test_v9_cache_rest.CacheRestTests.test_missing)\n"
                  "ERROR: test_config (test_v10_config.Modern.test_config)\n"
                  "Ran 2 tests in 0.001s\nFAILED (failures=1, errors=1)\n")
        g = target.classify_output(output)
        self.assertEqual(g["LEGACY_V8_V9"], {"FAIL": 1, "ERROR": 0})
        self.assertEqual(g["CURRENT_OTHER"], {"FAIL": 0, "ERROR": 1})

    def test_missing_dependency_path_is_reduced_to_basename(self):
        log = ("FileNotFoundError: [Errno 2] No such file or directory: "
               "'/home/runner/private/downloads/RUN_AI_COCKPIT_V9.ps1'\n"
               "FileNotFoundError: [Errno 2] No such file or directory: "
               "'C:\\work\\downloads\\RUN_AI_COCKPIT_V9.ps1'\n")
        counts = target.missing_dependency_summary(log)
        self.assertEqual(counts, {"RUN_AI_COCKPIT_V9.ps1": 2})
        self.assertNotIn("/home/runner", str(counts))
        self.assertNotIn("C:\\work", str(counts))

    def test_error_exit_is_preserved_exactly_without_group_reorder(self):
        fake = SimpleNamespace(returncode=1, stdout=(
            "FAIL: test_bad (test_v9_cache_rest.CacheRest.test_bad)\n"
            "Ran 1 test in 0.001s\nFAILED (failures=1)\n"))
        out = io.StringIO()
        with patch.object(target.subprocess, "run", return_value=fake) as p:
            with contextlib.redirect_stdout(out):
                code = target.main(["--tests", "tests"])
        self.assertEqual(code, 1)
        command = p.call_args.args[0]
        self.assertEqual(command, [sys.executable, "-m", "unittest", "discover",
                                   "-s", "tests", "-p", "test_*.py", "-v"])
        self.assertEqual(p.call_args.kwargs["check"], False)
        self.assertIn("P0_417_ORIGINAL_EXIT_CODE=1", out.getvalue())
        self.assertIn("P0_417_GROUP_FAILURES=LEGACY_V8_V9 FAIL=1 ERROR=0", out.getvalue())

    def test_success_exit_and_original_output_preserved(self):
        fake = SimpleNamespace(returncode=0, stdout="Ran 2 tests in 0.002s\nOK\n")
        out = io.StringIO()
        with patch.object(target.subprocess, "run", return_value=fake):
            with contextlib.redirect_stdout(out):
                code = target.main([])
        self.assertEqual(code, 0)
        self.assertIn("Ran 2 tests in 0.002s", out.getvalue())
        self.assertIn("P0_417_EXECUTED=2", out.getvalue())
        self.assertIn("P0_417_RESULT=PASS", out.getvalue())


if __name__ == "__main__":
    unittest.main()
