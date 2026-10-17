"""P0-417: analyze failures without changing unittest collection or execution.

Runs EXACTLY the old full-suite command, preserving its exit code; after it
finishes, classifies reported failures as legacy V8/V9 or current/other.
This runner MUST NOT filter tests, change suite order, or suppress failures.
"""
import argparse
import collections
import re
import subprocess
import sys


def classify(name):
    parts = name.split(".")
    module = parts[0]
    if "._FailedTest." in name:
        module = parts[-1]
    if module.startswith(("test_v8_", "test_v9_",
                          "test_ai_cockpit_v8_", "test_ai_cockpit_v9_")):
        return "LEGACY_V8_V9"
    return "CURRENT_OTHER"


def classify_output(output):
    groups = {"CURRENT_OTHER": {"FAIL": 0, "ERROR": 0},
              "LEGACY_V8_V9": {"FAIL": 0, "ERROR": 0}}
    # TextTestRunner prints one final 'FAIL: ...' or 'ERROR: ...' per failed test.
    for kind, name in re.findall(r"(?m)^(FAIL|ERROR):\s+[^\n(]+\(([^)]+)\)", output):
        groups[classify(name)][kind] += 1
    return groups


def missing_dependency_summary(output):
    # Never emit absolute runner paths; only safe source basenames.
    paths = re.findall(r"FileNotFoundError: \[Errno 2\] No such file or directory: '([^']+)'", output)
    return collections.Counter(path.replace("\\", "/").rsplit("/", 1)[-1] for path in paths)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", default="tests")
    args = parser.parse_args(argv)
    command = [sys.executable, "-m", "unittest", "discover",
               "-s", args.tests, "-p", "test_*.py", "-v"]
    print("P0_417_EXECUTION=UNCHANGED_FULL_UNITTEST_DISCOVERY", flush=True)
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", check=False)
    print(result.stdout, end="", flush=True)
    grouped = classify_output(result.stdout)
    for label in ("CURRENT_OTHER", "LEGACY_V8_V9"):
        x = grouped[label]
        print("P0_417_GROUP_FAILURES=" + label +
              " FAIL=" + str(x["FAIL"]) + " ERROR=" + str(x["ERROR"]), flush=True)
    missing = missing_dependency_summary(result.stdout)
    print("P0_417_MISSING_DEPENDENCIES=" + str(sum(missing.values())), flush=True)
    for filename, count in sorted(missing.items()):
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", filename):
            print("P0_417_MISSING_FILE=" + filename + " COUNT=" + str(count), flush=True)
        else:
            print("P0_417_MISSING_FILE=REDACTED COUNT=" + str(count), flush=True)
    summary = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+[\d.]+s", result.stdout)
    print("P0_417_EXECUTED=" + (summary.group(1) if summary else "UNKNOWN"), flush=True)
    print("P0_417_ORIGINAL_EXIT_CODE=" + str(result.returncode), flush=True)
    print("P0_417_RESULT=" + ("PASS" if result.returncode == 0 else "FAIL"), flush=True)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
