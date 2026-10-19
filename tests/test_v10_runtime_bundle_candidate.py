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
        self.assertEqual(len(self.pins), 31)
        self.assertEqual(len(self.manifest["files"]), 31)
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
        self.assertIn("V10_RELEASE_SOURCE_BLOBS_MATCH=31", self.entry)
        self.assertIn("V10_START_PREFLIGHT=PASS_NO_RUNTIME", self.entry)

    def test_owner_run_and_stop_remain_separate(self):
        self.assertTrue((ROOT / "downloads" / "STOP_AI_COCKPIT_V10.ps1").is_file())
        self.assertTrue((ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1").is_file())
        self.assertIn("V10_RELEASE_COMPONENTS_PRESENT=1", self.entry)
        self.assertNotIn("Stop-Process", self.entry)
        self.assertNotIn("Start-Process", self.entry)


class V10LaunchDependencyLineage(unittest.TestCase):
    """P0-V10-MARKET-OPERABILITY-20261019 P0-6: every local file that START,
    RUN, the Controller or STOP loads from the checkout is tracked, pinned in
    the manifest and required by START before any worker starts."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
        cls.pins = {x["path"]: x["git_blob_sha"] for x in cls.manifest["files"]}
        cls.entry = ENTRY.read_text(encoding="utf-8-sig")
        block = re.search(r"\$required = @\((.*?)\)\s*foreach", cls.entry, re.S)
        cls.required = re.findall(r'"([^"]+)"', block.group(1))
        read = lambda rel: (ROOT / rel).read_text(encoding="utf-8-sig")
        cls.runner = read("downloads/RUN_AI_COCKPIT_V10.ps1")
        cls.controller = read("downloads/AI_COCKPIT_CONTROLLER_V10.ps1")
        cls.stop = read("downloads/STOP_AI_COCKPIT_V10.ps1")

    def test_every_runtime_deploy_file_is_required_and_pinned(self):
        block = re.search(r"\$RUNTIME_DEPLOY_FILES = @\((.*?)\)", self.runner, re.S)
        deployed = re.findall(r'"([^"]+)"', block.group(1))
        self.assertIn("watchlist_100.json", deployed)
        for name in deployed:
            with self.subTest(file=name):
                self.assertIn("ms2_live/" + name, self.required)
                self.assertIn("ms2_live/" + name, self.pins)

    def test_controller_runtime_check_matches_the_deploy_list(self):
        deployed = set(re.findall(r'"([^"]+)"', re.search(r"\$RUNTIME_DEPLOY_FILES = @\((.*?)\)", self.runner, re.S).group(1)))
        checked = re.search(r"foreach \(\$name in @\((.*?)\)\)\s*\{\s*\$expectedHash", self.controller, re.S)
        self.assertIsNotNone(checked)
        self.assertEqual(set(re.findall(r'"([^"]+)"', checked.group(1))), deployed)

    def test_repo_scripts_loaded_by_the_controller_are_pinned(self):
        loaded = set(re.findall(r'Join-Path \$RepoRootResolved "(scripts\\[^"]+\.py)"', self.controller))
        self.assertTrue(loaded)
        for rel in loaded:
            with self.subTest(file=rel):
                self.assertIn(rel.replace("\\", "/"), self.pins)

    def test_required_files_are_tracked_and_match_their_pins(self):
        self.assertEqual(set(self.required), set(self.pins))
        tracked = set(subprocess.run(["git", "-C", str(ROOT), "ls-files"], check=True, capture_output=True,
                                     text=True).stdout.splitlines())
        for rel in self.required:
            with self.subTest(file=rel):
                self.assertIn(rel, tracked)
                blob = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD:" + rel], check=True,
                                      capture_output=True, text=True).stdout.strip()
                self.assertEqual(blob, self.pins[rel])

    def test_missing_component_fails_before_any_worker(self):
        missing = self.entry.index("V10_RELEASE_COMPONENT_MISSING")
        blobs = self.entry.index("V10_RELEASE_SOURCE_BLOB_MISMATCH")
        launch = self.entry.index("-File $runner")
        self.assertLess(missing, launch)
        self.assertLess(blobs, launch)

    def test_no_code_is_loaded_from_the_state_root_or_an_old_install(self):
        for name, text in (("controller", self.controller), ("stop", self.stop), ("runner", self.runner),
                           ("start", self.entry)):
            with self.subTest(script=name):
                self.assertNotIn("AI_Cockpit_Current", text)
                for target in re.findall(r'Join-Path \$Root "([^"]+)"', text):
                    self.assertTrue(target.endswith(".json") or target.startswith("Logs"), target)

    def test_stop_command_is_part_of_the_candidate(self):
        cmd = (ROOT / "downloads" / "STOP_AI_COCKPIT_V10.cmd").read_text(encoding="utf-8")
        self.assertIn("%~dp0STOP_AI_COCKPIT_V10.ps1", cmd)
        self.assertIn("downloads/STOP_AI_COCKPIT_V10.ps1", self.pins)

if __name__ == "__main__":
    unittest.main()
