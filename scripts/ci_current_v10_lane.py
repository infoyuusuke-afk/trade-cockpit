"""P0-417: explicit CURRENT synthetic lane; historical tests stay in original CI.

This lane is additional and never replaces the monolithic FAIL-visible job.
Only explicitly archived V8/V9 cases can be omitted from this current-only lane.
Their historic SHA-pinned source is separately tested in the acceptance matrix.
"""
import os
import re
import sys
import unittest

HISTORIC_MODULE_PREFIXES = (
    "test_v8_", "test_v9_", "test_ai_cockpit_v8_", "test_ai_cockpit_v9_",
)
HISTORIC_MODULES = {"test_collector_workbook_identity"}
HISTORIC_TEST_IDS = {
    "test_ai_shadow_supervisor.ContractSourceTests.test_controller_and_gateway_keep_real_submit_locked",
}
HISTORY_COMMIT = "b81b8877b12a33368e91e5e156a2fc7ac4529349"


def is_historic(test_id):
    module = test_id.split(".", 1)[0]
    if "._FailedTest." in test_id:
        module = test_id.rsplit(".", 1)[-1]
    return (module.startswith(HISTORIC_MODULE_PREFIXES) or
            module in HISTORIC_MODULES or test_id in HISTORIC_TEST_IDS)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def partition_discovery(suite):
    current = unittest.TestSuite()
    historical = []
    current_ids = []
    for item in flatten(suite):
        identity = item.id()
        if is_historic(identity):
            historical.append(identity)
        else:
            current.addTest(item)
            current_ids.append(identity)
    if not historical or not current_ids or len(set(current_ids + historical)) != len(current_ids) + len(historical):
        raise RuntimeError("P0_417_DISCOVERY_INVENTORY_UNSAFE")
    if not HISTORIC_TEST_IDS.issubset(set(historical)):
        raise RuntimeError("P0_417_HISTORIC_SHADOW_CONTRACT_MISSING")
    return current, historical, current_ids


def main():
    # Match `python -m unittest discover` import resolution from repo root.
    sys.path.insert(0, os.getcwd())
    suite = unittest.TestLoader().discover("tests", pattern="test_*.py")
    current, historical, current_ids = partition_discovery(suite)
    print("P0_417_CURRENT_LANE=ADDITIONAL_NOT_REPLACING_MONOLITH", flush=True)
    print("P0_417_HISTORIC_SOURCE_COMMIT=" + HISTORY_COMMIT, flush=True)
    print("P0_417_DISCOVERED=" + str(len(current_ids) + len(historical)), flush=True)
    print("P0_417_CURRENT_COUNT=" + str(len(current_ids)), flush=True)
    print("P0_417_HISTORIC_EXPLICIT_COUNT=" + str(len(historical)), flush=True)
    print("P0_417_HISTORIC_EXPLICIT_IDS=" + str(len(set(historical))), flush=True)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(current)
    print("P0_417_CURRENT_RESULT=" + ("PASS" if result.wasSuccessful() else "FAIL"), flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
