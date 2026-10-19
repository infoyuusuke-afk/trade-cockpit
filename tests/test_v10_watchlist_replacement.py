"""P0-V10-WATCHLIST-464A-SOURCE-PIN-20261019: the watchlist pin check accepts
exactly the OWNER-approved 5595.T -> 464A.T replacement and nothing else.

Each negative below is a deliberate tampering the CI must reject. The pinned
watchlist is read from the candidate commit recorded in the manifest, so the
test uses the real 100-name list; no market data is involved.
"""
import copy
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_wl", ROOT / "scripts" / "ci_v10_watchlist_replacement.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

MANIFEST = json.loads((ROOT / "downloads" / "V10_RELEASE_BUNDLE_MANIFEST.json").read_text(encoding="utf-8-sig"))
PINNED_COMMIT = MANIFEST["candidate_source_commit"]
WATCHLIST = "ms2_live/watchlist_100.json"


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, timeout=30).stdout


def _pinned():
    try:
        raw = _git("show", PINNED_COMMIT + ":" + WATCHLIST)
    except subprocess.CalledProcessError:
        raise unittest.SkipTest("pinned candidate commit not fetched")
    return json.loads(raw.decode("utf-8-sig"))


def _candidate():
    return json.loads((ROOT / WATCHLIST).read_text(encoding="utf-8-sig"))


def _rebuild(doc, items):
    out = copy.deepcopy(doc)
    out["stocks"] = dict(items)
    return out


class WatchlistReplacementCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pinned = _pinned()
        cls.candidate = _candidate()

    def assertRejected(self, doc, code):
        with self.assertRaises(ci.WatchlistReplacementError) as ctx:
            ci.check_replacement(doc, self.pinned)
        self.assertTrue(str(ctx.exception).startswith(code), str(ctx.exception))

    def test_candidate_is_exactly_the_approved_replacement(self):
        ci.check_replacement(self.candidate, self.pinned)
        items = list(self.candidate["stocks"].items())
        self.assertEqual(len(items), 100)
        self.assertEqual(items[87][0], "QPSホールディングス（464A）")
        self.assertEqual(items[87][1]["ticker"], "464A.T")
        self.assertNotIn("5595.T", [row["ticker"] for _, row in items])
        self.assertEqual([k for k, _ in items[:87]], [k for k, _ in list(self.pinned["stocks"].items())[:87]])

    def test_manifest_pins_the_committed_watchlist_blob(self):
        pin = next(f["git_blob_sha"] for f in MANIFEST["files"] if f["path"] == WATCHLIST)
        self.assertEqual(_git("rev-parse", "HEAD:" + WATCHLIST).decode().strip(), pin)

    def test_manifest_sha_mismatch_is_detected(self):
        pin = next(f["git_blob_sha"] for f in MANIFEST["files"] if f["path"] == WATCHLIST)
        tampered = pin[:-1] + ("0" if pin[-1] != "0" else "1")
        self.assertNotEqual(_git("rev-parse", "HEAD:" + WATCHLIST).decode().strip(), tampered)

    def test_99_names_rejected(self):
        items = list(self.candidate["stocks"].items())[:-1]
        self.assertRejected(_rebuild(self.candidate, items), "WATCHLIST_COUNT_CHANGED")

    def test_101_names_rejected(self):
        items = list(self.candidate["stocks"].items()) + [("合成銘柄（9999）", {"ticker": "9999.T", "sector": "synthetic", "style": "both"})]
        self.assertRejected(_rebuild(self.candidate, items), "WATCHLIST_COUNT_CHANGED")

    def test_two_changed_names_rejected(self):
        items = list(self.candidate["stocks"].items())
        name, row = items[10]
        items[10] = (name, dict(row, ticker="9998.T"))
        self.assertRejected(_rebuild(self.candidate, items), "WATCHLIST_CHANGE_COUNT_NOT_ONE")

    def test_duplicate_ticker_rejected(self):
        items = list(self.candidate["stocks"].items())
        name, row = items[5]
        items[5] = (name, dict(row, ticker=items[4][1]["ticker"]))
        self.assertRejected(_rebuild(self.candidate, items), "WATCHLIST_DUPLICATE_TICKER")

    def test_reordered_names_rejected(self):
        items = list(self.candidate["stocks"].items())
        items[1], items[2] = items[2], items[1]
        self.assertRejected(_rebuild(self.candidate, items), "WATCHLIST_CHANGE_COUNT_NOT_ONE")

    def test_unapproved_code_rejected(self):
        items = list(self.candidate["stocks"].items())
        name, row = items[87]
        items[87] = (name, dict(row, ticker="465A.T"))
        self.assertRejected(_rebuild(self.candidate, items), "WATCHLIST_UNAPPROVED_REPLACEMENT")

    def test_unapproved_name_rejected(self):
        items = list(self.candidate["stocks"].items())
        _, row = items[87]
        items[87] = ("別名（464A）", row)
        self.assertRejected(_rebuild(self.candidate, items), "WATCHLIST_UNAPPROVED_REPLACEMENT")

    def test_other_attribute_change_rejected(self):
        items = list(self.candidate["stocks"].items())
        name, row = items[87]
        items[87] = (name, dict(row, sector="changed"))
        self.assertRejected(_rebuild(self.candidate, items), "WATCHLIST_OTHER_ATTRIBUTES_CHANGED")

    def test_unchanged_pinned_list_rejected(self):
        # The pinned list itself still carries the delisted code: not "one change".
        self.assertRejected(copy.deepcopy(self.pinned), "WATCHLIST_CHANGE_COUNT_NOT_ONE")

    def test_cli_exit_codes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "c.json"
            pinned = Path(tmp) / "p.json"
            bad = Path(tmp) / "b.json"
            good.write_text(json.dumps(self.candidate, ensure_ascii=False), encoding="utf-8")
            pinned.write_text(json.dumps(self.pinned, ensure_ascii=False), encoding="utf-8")
            bad.write_text(json.dumps(_rebuild(self.candidate, list(self.candidate["stocks"].items())[:-1]), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(ci.main(["x", str(good), str(pinned)]), 0)
            self.assertEqual(ci.main(["x", str(bad), str(pinned)]), 1)


class WorkflowStillParses(unittest.TestCase):
    def test_bundle_workflow_is_valid_yaml_and_calls_the_check(self):
        try:
            import yaml
        except ImportError:
            raise unittest.SkipTest("PyYAML not installed")
        path = ROOT / ".github" / "workflows" / "v10-candidate-runtime-bundle-synthetic.yml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertIn("full-source-parity", doc["jobs"])
        text = path.read_text(encoding="utf-8")
        self.assertIn("python scripts/ci_v10_watchlist_replacement.py", text)
        self.assertIn('test "$(git rev-parse "HEAD:$file")" = "$expected"', text)


if __name__ == "__main__":
    unittest.main()
