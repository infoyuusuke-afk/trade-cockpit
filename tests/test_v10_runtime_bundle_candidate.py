"""V10 full release-candidate bundle integrity checks; no live runtime.

These contracts verify that the reviewed V10 engine + UI source candidate is
present exactly as recorded in the tracked 28-file Git blob manifest.
A green result is NOT an independent approval for production or real orders.
"""
import json
import re
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "downloads" / "V10_RELEASE_BUNDLE_MANIFEST.json"
ENTRY = ROOT / "downloads" / "START_AI_COCKPIT_V10.ps1"
INDEX = ROOT / "index.html"
REFERENCE = "e906dedc45448ca20428a7ca1afa1126eaeeedaa"


class LocalAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.files = set()

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag not in ("script", "link"):
            return
        url = data.get("src") or data.get("href") or ""
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return
        suffix = Path(parsed.path).suffix.lower()
        if suffix in (".js", ".css"):
            self.files.add(parsed.path.lstrip("./"))


class V10BundleCandidateContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
        cls.pins = {x["path"]: x["git_blob_sha"] for x in cls.manifest["files"]}
        cls.runner = (ROOT / "downloads" / "RUN_AI_COCKPIT_V10.ps1").read_text(
            encoding="utf-8-sig"
        )
        cls.entry = ENTRY.read_text(encoding="utf-8-sig")

    def test_candidate_pin_not_a_production_approval(self):
        self.assertEqual(self.manifest["schema"], "v10_release_candidate_blobs_v1")
        self.assertEqual(self.manifest["candidate_source_commit"], REFERENCE)
        self.assertIs(self.manifest["real_submit_allowed"], False)
        self.assertFalse((ROOT / "downloads" / "V10_APPROVED_SOURCE.json").exists())

    def test_manifest_exact_paths_and_count(self):
        self.assertEqual(len(self.pins), 30)
        self.assertEqual(len(self.manifest["files"]), 30)
        block = re.search(r"\$required = @\((.*?)\)\s*foreach", self.entry, re.S)
        self.assertIsNotNone(block)
        checked = set(re.findall(r'"([^"]+)"', block.group(1)))
        self.assertEqual(checked, set(self.pins))

    def test_all_pinned_assets_are_tracked_blob_ids(self):
        for path, sha in self.pins.items():
            with self.subTest(path=path):
                item = ROOT / Path(path)
                self.assertTrue(item.is_file(), path)
                self.assertRegex(sha, r"^[0-9a-f]{40}$")
                cmd = subprocess.run(["git", "rev-parse", "HEAD:" + path],
                                     cwd=ROOT, check=True, capture_output=True,
                                     text=True, timeout=15)
                self.assertEqual(cmd.stdout.strip(), sha)

    def test_initial_ui_script_and_style_references_present_and_pinned(self):
        parser = LocalAssets()
        parser.feed(INDEX.read_text(encoding="utf-8-sig"))
        self.assertGreaterEqual(len(parser.files), 12)
        for name in parser.files:
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).is_file(), name)
                self.assertIn(name, self.pins, "UI source dependency is not pinned: " + name)

    def test_full_runner_requires_owner_pin_and_disallows_direct_bypass(self):
        for marker in (
            "V10_MUTATING_START_REQUIRES_APPROVAL_FILE",
            "PINNED_SHA_MUST_BE_FULL_40_HEX",
            "V10_WORKTREE_NOT_CLEAN",
            "REAL_SUBMIT_ALLOWED=0",
        ):
            self.assertIn(marker, self.runner)
        self.assertIn("V10_RELEASE_SOURCE_BLOBS_MATCH=30", self.entry)
        self.assertIn("V10_START_PREFLIGHT=PASS_NO_RUNTIME", self.entry)

    def test_controller_excel_identity_dependency_is_always_tracked(self):
        helper = "downloads/EXCEL_IDENTITY_PROBE_V10.ps1"
        self.assertIn(helper, self.pins)
        controller = (ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('Join-Path $PSScriptRoot "EXCEL_IDENTITY_PROBE_V10.ps1"', controller)
        self.assertTrue((ROOT / helper).is_file())

    def test_owner_run_and_stop_remain_separate(self):
        self.assertTrue((ROOT / "downloads" / "STOP_AI_COCKPIT_V10.ps1").is_file())
        self.assertTrue((ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1").is_file())
        self.assertIn("V10_RELEASE_COMPONENTS_PRESENT=1", self.entry)
        self.assertNotIn("Stop-Process", self.entry)
        self.assertNotIn("Start-Process", self.entry)


if __name__ == "__main__":
    unittest.main()
