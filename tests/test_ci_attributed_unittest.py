"""P0-417: synthetic tests of fail-visible attribution; does not run live scripts."""
import contextlib
import io
import tempfile
import textwrap
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci_attributed_unittest as target


class FakeCase(unittest.TestCase):
    def test_stub(self):
        pass


class AttributionTests(unittest.TestCase):
    def test_classification_covers_legacy_and_loader_failure(self):
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

    def test_grouping_never_drops_a_test(self):
        case = FakeCase("test_stub")
        nested = unittest.TestSuite([unittest.TestSuite([case])])
        groups, ids = target.make_groups(nested)
        self.assertEqual(ids, [case.id()])
        self.assertEqual(sum(x.countTestCases() for x in groups.values()), 1)

    def test_mixed_pass_fail_preserves_failure_exit(self):
        with tempfile.TemporaryDirectory(prefix="p0417-synthetic-") as tmp:
            folder = Path(tmp)
            (folder / "test_regular.py").write_text(textwrap.dedent("""
                import unittest
                class Current(unittest.TestCase):
                    def test_pass(self): self.assertTrue(True)
            """), encoding="utf-8")
            (folder / "test_v9_legacy.py").write_text(textwrap.dedent("""
                import unittest
                class Legacy(unittest.TestCase):
                    def test_fail(self): self.assertEqual(1, 2)
            """), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = target.main(["--tests", str(folder)])
            self.assertEqual(code, 1)
            text = stdout.getvalue()
            self.assertIn("P0_417_DISCOVERED=2", text)
            self.assertIn("P0_417_GROUP_RESULT=CURRENT_OTHER:PASS", text)
            self.assertIn("P0_417_GROUP_RESULT=LEGACY_V8_V9:FAIL", text)
            self.assertIn("P0_417_RESULT=FAIL", text)

    def test_only_current_tests_can_pass(self):
        with tempfile.TemporaryDirectory(prefix="p0417-synthetic-") as tmp:
            folder = Path(tmp)
            (folder / "test_current_only.py").write_text(textwrap.dedent("""
                import unittest
                class Current(unittest.TestCase):
                    def test_pass(self): self.assertTrue(True)
            """), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = target.main(["--tests", str(folder)])
            self.assertEqual(code, 0)
            self.assertIn("P0_417_RESULT=PASS", output.getvalue())


if __name__ == "__main__":
    unittest.main()
