"""P0-33: run the full current unittest inventory minus the pinned V8/V9 legacy IDs.

Fail-closed rules:
- Only test IDs listed in scripts/ci_legacy_v8_v9_excluded.txt are excluded.
- An excluded ID must live in a module that references a downloads/*_V8*/*_V9*
  script which is absent from this checkout (D-003). Otherwise the run fails.
- No V10 test may be listed, and the mobile/order-safety suites must run.
- Any failure, error or import error in the remaining tests fails the job.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
LIST = ROOT / "scripts" / "ci_legacy_v8_v9_excluded.txt"
REQUIRED_MODULES = (
    "test_mobile_approvals",
    "test_owner_approval_queue",
    "test_execution_contract",
    "test_execution_contract_boundary",
    "test_execution_permission",
    "test_autonomy_gate",
)
LEGACY_REF = re.compile(r'"([A-Za-z0-9_]+_V[89](?:_[A-Za-z0-9_]+)?\.ps1)"')


def load_excluded():
    ids = []
    for line in LIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.append(line)
    if len(ids) != len(set(ids)):
        raise SystemExit("LEGACY_LIST_DUPLICATE")
    return set(ids)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def missing_legacy_refs(module):
    source = (TESTS / (module + ".py")).read_text(encoding="utf-8")
    return [name for name in LEGACY_REF.findall(source)
            if not (ROOT / "downloads" / name).exists()]



def verify_exclusion_ids(excluded, discovered_ids):
    absent = sorted(excluded - discovered_ids)
    if absent:
        raise SystemExit("LEGACY_LIST_ID_NOT_DISCOVERED: " + ",".join(absent))


def main():
    excluded = load_excluded()
    for test_id in excluded:
        if re.search(r"v10", test_id, re.IGNORECASE):
            raise SystemExit("LEGACY_LIST_NAMES_V10: " + test_id)
    # Same import roots as `python -m unittest discover -s tests` run from ROOT.
    sys.path[:0] = [str(ROOT), str(TESTS)]
    tests = list(flatten(unittest.defaultTestLoader.discover(str(TESTS), pattern="test_*.py", top_level_dir=str(TESTS))))
    # Fail closed when an excluded test was renamed/removed or discovery changed.
    # Never silently accept a stale list that no longer matches collected IDs.
    verify_exclusion_ids(excluded, {test.id() for test in tests})
    kept, skipped = [], []
    for test in tests:
        (skipped if test.id() in excluded else kept).append(test)
    for module in sorted({t.id().split(".")[0] for t in skipped}):
        if not missing_legacy_refs(module):
            raise SystemExit("LEGACY_EXCLUSION_NOT_PROVEN: " + module
                             + " references no missing V8/V9 script")
    # An import failure surfaces as unittest.loader._FailedTest.<module> and
    # still fails the run below; it counts as collected, never as skipped.
    present = {t.id().split(".")[-1] if t.id().startswith("unittest.loader._FailedTest.")
               else t.id().split(".")[0] for t in kept}
    absent = [m for m in REQUIRED_MODULES
              if m not in present or not (TESTS / (m + ".py")).is_file()]
    if absent:
        raise SystemExit("MOBILE_SAFETY_SUITE_MISSING: " + ",".join(absent))
    print("CURRENT_TESTS=%d LEGACY_V8_V9_EXCLUDED=%d LEGACY_LISTED=%d"
          % (len(kept), len(skipped), len(excluded)))
    for test in skipped:
        print("EXCLUDED_LEGACY " + test.id())
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(kept))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
