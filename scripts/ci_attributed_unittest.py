"""P0-417: execute *every* discovered unittest while attributing old V8/V9 failures.

This runner never filters, skips, or rewrites a failing test. It separates
legacy V8/V9 tests from modern tests for accountable GitHub Actions output.
The overall exit code remains nonzero when EITHER group fails.
"""
import argparse
import sys
import unittest
from pathlib import Path


def classify(test_id):
    # Discover can produce unittest.loader._FailedTest.<module> entries.
    module = test_id.split(".", 1)[0]
    if "._FailedTest." in test_id:
        module = test_id.rsplit(".", 1)[-1]
    if (module.startswith(("test_v8_", "test_v9_",
                           "test_ai_cockpit_v8_", "test_ai_cockpit_v9_"))):
        return "LEGACY_V8_V9"
    return "CURRENT_OTHER"


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def make_groups(suite):
    groups = {"CURRENT_OTHER": unittest.TestSuite(), "LEGACY_V8_V9": unittest.TestSuite()}
    seen = []
    for case in flatten(suite):
        seen.append(case.id())
        groups[classify(case.id())].addTest(case)
    return groups, seen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", default="tests")
    args = parser.parse_args(argv)
    root = Path(args.tests)
    loader = unittest.TestLoader()
    suite = loader.discover(str(root), pattern="test_*.py")
    groups, ids = make_groups(suite)
    if len(ids) != len(set(ids)):
        print("P0_417_RESULT=DISCOVERY_DUPLICATE_IDS", flush=True)
        return 2
    print("P0_417_DISCOVERED=" + str(len(ids)), flush=True)
    print("P0_417_TEST_GROUPS=CURRENT_OTHER,LEGACY_V8_V9", flush=True)
    passed = True
    total = 0
    for label, cases in groups.items():
        count = cases.countTestCases()
        total += count
        print("P0_417_GROUP=" + label + " COUNT=" + str(count), flush=True)
        result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(cases)
        print("P0_417_GROUP_RESULT=" + label + ":" +
              ("PASS" if result.wasSuccessful() else "FAIL") +
              " FAILURES=" + str(len(result.failures)) +
              " ERRORS=" + str(len(result.errors)) +
              " SKIPPED=" + str(len(result.skipped)), flush=True)
        passed = passed and result.wasSuccessful()
    if total != len(ids):
        print("P0_417_RESULT=DISCOVERY_COUNT_MISMATCH", flush=True)
        return 2
    print("P0_417_RESULT=" + ("PASS" if passed else "FAIL"), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
