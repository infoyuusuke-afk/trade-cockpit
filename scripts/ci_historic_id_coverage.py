"""P0-417: auditable old-test ID correspondence, not a test waiver.

Lists historical cases actually executed by the pinned CI: V8 contract,
V9 diagnostics, and historic Collector. New current-source archived cases
without the exact historic test ID are explicitly UNMAPPED, not PASS.
No writes to source; checkout and tests remain isolated.
"""
import ast
import collections
import pathlib
import sys

CURRENT = pathlib.Path(__file__).resolve().parents[1]
PIN = "b81b8877b12a33368e91e5e156a2fc7ac4529349"
PREFIXES = ("test_v8_", "test_v9_", "test_ai_cockpit_v8_", "test_ai_cockpit_v9_")
EXTRAS = {"test_collector_workbook_identity"}
EXACT = {"test_ai_shadow_supervisor.ContractSourceTests.test_controller_and_gateway_keep_real_submit_locked"}


def test_ids(root):
    paths = sorted((root / "tests").glob("test_*.py"))
    result = {}
    for p in paths:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8-sig"), filename=p.name)
        except (SyntaxError, UnicodeError):
            raise RuntimeError("P0_417_UNPARSEABLE_TEST=" + p.name)
        names = []
        for obj in tree.body:
            if isinstance(obj, ast.ClassDef):
                for method in obj.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith("test_"):
                        names.append(p.stem + "." + obj.name + "." + method.name)
        result[p.stem] = names
    return result


def classify_id(x):
    module = x.split(".", 1)[0]
    return module.startswith(PREFIXES) or module in EXTRAS or x in EXACT


def audit(current, historical):
    current_ids = {x for group in test_ids(current).values() for x in group if classify_id(x)}
    old = test_ids(historical)
    historic_executed = {x for module, group in old.items()
                         if module == "test_ai_cockpit_v8_controller_contract" or
                            module == "test_collector_workbook_identity" or
                            module.startswith("test_v9_")
                         for x in group}
    unmapped = sorted(current_ids - historic_executed)
    old_only = sorted(historic_executed - current_ids)
    return {"current_archive":len(current_ids), "historical_executed":len(historic_executed),
            "exact_matched":len(current_ids & historic_executed),
            "unmapped":unmapped, "historical_only":old_only}


def main(argv):
    if len(argv) != 1:
        raise SystemExit("Usage: ci_historic_id_coverage.py HISTORICAL_CHECKOUT")
    root = pathlib.Path(argv[0]).resolve(strict=True)
    report = audit(CURRENT, root)
    for key in ("current_archive", "historical_executed", "exact_matched"):
        print("P0_417_COVERAGE_" + key.upper() + "=" + str(report[key]), flush=True)
    print("P0_417_COVERAGE_UNMAPPED=" + str(len(report["unmapped"])), flush=True)
    print("P0_417_COVERAGE_HISTORIC_ONLY=" + str(len(report["historical_only"])), flush=True)
    for ident in report["unmapped"]:
        print("P0_417_UNMAPPED_ID=" + ident, flush=True)
    print("P0_417_COVERAGE_RESULT=" + ("COMPLETE" if not report["unmapped"] else "GAP_PRESENT"), flush=True)
    return 0 if not report["unmapped"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
