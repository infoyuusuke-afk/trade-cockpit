"""P0-22 DPAPI CurrentUser private mapping: Windows-only disposable fixtures.

Creates no user-profile, real Starter, broker or Excel files.
No restoration of original CMD/LNK is performed.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "downloads" / "VERIFY_V10_RESTORE_TARGET_MAP.ps1"
VERIFIER = ROOT / "downloads" / "VERIFY_V10_ENCRYPTED_RESTORE_MAP.ps1"

@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "DPAPI CurrentUser is Windows-only; synthetic GitHub runner required",
)
class PrivateMapFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="p0-22-",dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.repo=self.root/"local-checkout"
        (self.repo/"downloads").mkdir(parents=True)
        self.state=self.root/"local-starter"
        self.state.mkdir()
        self.desktop1=self.root/"active-desktop"
        self.desktop2=self.root/"shortcut-desktop"
        self.desktop1.mkdir()
        self.desktop2.mkdir()
        self.snapshot=self.root/"20261017_044407_abcdefgh1234"
        self.snapshot.mkdir()
        self.files={
            "starter/START_AI_COCKPIT.ps1":(self.state/"START_AI_COCKPIT.ps1",b"# legacy starter"),
            "starter/AI_COCKPIT_START_DEBUG.cmd":(self.state/"AI_COCKPIT_START_DEBUG.cmd",b"@echo off legacy"),
            "repo/RUN_AI_COCKPIT_V10.ps1":(self.repo/"downloads"/"RUN_AI_COCKPIT_V10.ps1",b"# V10 old RUN"),
            "repo/STOP_AI_COCKPIT_V10.ps1":(self.repo/"downloads"/"STOP_AI_COCKPIT_V10.ps1",b"# V10 old STOP"),
            "repo/AI_COCKPIT_CONTROLLER_V10.ps1":(self.repo/"downloads"/"AI_COCKPIT_CONTROLLER_V10.ps1",b"# V10 old Controller"),
            "desktop1/AI Cockpit STOP.cmd":(self.desktop2/"AI Cockpit STOP.cmd",b"synthetic stop cmd"),
            "desktop2/AI Cockpit START.lnk":(self.desktop1/"AI Cockpit START.lnk",b"synthetic lnk bytes"),
        }
        entries=[]
        for rel,(active,data) in self.files.items():
            active.parent.mkdir(parents=True,exist_ok=True)
            active.write_bytes(data)
            src=self.snapshot/rel
            src.parent.mkdir(parents=True,exist_ok=True)
            src.write_bytes(data)
            entries.append({"name":rel,"sha256":hashlib.sha256(data).hexdigest().upper(),
                            "bytes":len(data)})
        self.manifest={
            "schema":"v10_cutover_backup_v1",
            "evidence_only":True,
            "no_changes_to_active_files":True,
            "real_submit_allowed":False,
            "source_pin_match":False,
            "desktop_inventory_complete":False,
            "unverified_desktop_indexes":[3],
            "unverified_desktop_actions":["DESKTOP_ATTRIBUTES"],
            "cutover_eligible":False,
            "files":entries
        }
        self.write_manifest()

    def write_manifest(self):
        (self.snapshot/"manifest.json").write_text(
            json.dumps(self.manifest),encoding="utf-8")

    def run_script(self, script, opts):
        def q(text):
            return "'"+str(text).replace("'","''")+"'"
        arguments=" ".join(f"-{key} {q(val)}" for key,val in opts.items())
        command=f"& {q(script)} {arguments}"
        encoded=base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        return subprocess.run(
            ["powershell.exe","-NoProfile","-NonInteractive",
             "-EncodedCommand",encoded],
            capture_output=True,text=True,errors="replace",timeout=35
        )

    def scan(self, save=True, roots=None):
        if roots is None:
            roots=[self.desktop1,self.desktop2]
        # Compose PowerShell array literals; no uncontrolled shell execution.
        def q(v):
            return "'"+str(v).replace("'","''")+"'"
        command=(
            f"& {q(SCANNER)} -Snapshot {q(self.snapshot)} "
            f"-RepoRoot {q(self.repo)} -StateRoot {q(self.state)} "
            f"-DesktopRoots @({','.join(q(p) for p in roots)})"
            + (" -SaveEncryptedMap" if save else "")
        )
        encoded=base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        return subprocess.run(
            ["powershell.exe","-NoProfile","-NonInteractive",
             "-EncodedCommand",encoded],
            capture_output=True,text=True,errors="replace",timeout=35
        )

    def make_map(self):
        result=self.scan()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("ENCRYPTED_MAP_RESULT=SAVED_PRIVATE_ONLY",result.stdout)
        ids=re.findall(r"(?m)^ENCRYPTED_MAP_ID=([0-9a-f]{32})\s*$",result.stdout)
        self.assertEqual(len(ids),1,result.stdout)
        return ids[0]

    def verify(self,map_id):
        return self.run_script(VERIFIER,{"MapId":map_id,
                       "RepoRoot":self.repo,"StateRoot":self.state})

    def get_cipher_path(self,map_id):
        return self.state/"V10_private_restore_maps"/(map_id+".dpapi")

    def assert_safe(self, result):
        self.assertIn("REAL_SUBMIT_ALLOWED=false",result.stdout)
        self.assertIn("CUTOVER_ELIGIBLE=false",result.stdout)
        self.assertNotIn(str(self.root),result.stdout)
        self.assertNotIn("LIVE_FILES_MODIFIED=true",result.stdout)

    def test_encrypt_and_independently_reverify_partial_map(self):
        before={str(p.relative_to(self.root)):p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}
        map_id=self.make_map()
        cipher=self.get_cipher_path(map_id).read_bytes()
        self.assertNotIn(str(self.desktop1).encode("utf-8"),cipher)
        self.assertNotIn(str(self.state).encode("utf-8"),cipher)
        self.assertNotIn(b"START_AI_COCKPIT.ps1",cipher)
        self.assertGreater(len(cipher),100)
        p=self.verify(map_id)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        for marker in ("MAP_RECHECK_MATCHED=7","MAP_RECHECK_STALE=0",
                       "MAP_TOTAL_ARCHIVED=7","MAP_INVENTORY_PARTIAL=true",
                       "ENCRYPTED_MAP_RECEIPT=VERIFIED_PARTIAL_HOLD",
                       "ABSOLUTE_PATHS_EXPORTED=false"):
            self.assertIn(marker,p.stdout)
        self.assert_safe(p)
        # Snapshot, live source and launcher copies must not have changed.
        for path,data in before.items():
            self.assertEqual((self.root/path).read_bytes(),data)

    def test_default_scan_never_creates_map(self):
        p=self.scan(save=False)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("TARGET_MAP_STATUS=PARTIAL_HOLD",p.stdout)
        self.assertFalse((self.state/"V10_private_restore_maps").exists())
        self.assert_safe(p)

    def test_stale_file_detected_without_replacing_it(self):
        map_id=self.make_map()
        path=self.state/"START_AI_COCKPIT.ps1"
        path.write_bytes(b"changed since protected map")
        p=self.verify(map_id)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("MAP_RECHECK_STALE=1",p.stdout)
        self.assertIn("ENCRYPTED_MAP_RECEIPT=STALE_HOLD",p.stdout)
        self.assertEqual(path.read_bytes(),b"changed since protected map")
        self.assert_safe(p)

    def test_ciphertext_tamper_is_rejected(self):
        map_id=self.make_map()
        file=self.get_cipher_path(map_id)
        data=bytearray(file.read_bytes())
        data[len(data)//2]^=0x5A
        file.write_bytes(data)
        p=self.verify(map_id)
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("ENCRYPTED_MAP_RECEIPT=BLOCKED",p.stdout)
        self.assert_safe(p)

    def test_snapshot_manifest_tamper_refuses_independent_verification(self):
        map_id=self.make_map()
        self.manifest["files"][0]["sha256"]="0"*64
        self.write_manifest()
        p=self.verify(map_id)
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("ENCRYPTED_MAP_RECEIPT=BLOCKED",p.stdout)
        self.assert_safe(p)

    def test_invalid_identifier_cannot_access_other_files(self):
        p=self.verify("..\\account-file")
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("BLOCK_REASON=BAD_MAP_ID",p.stdout)
        self.assertIn("ENCRYPTED_MAP_RECEIPT=BLOCKED",p.stdout)
        self.assert_safe(p)

    def test_two_identical_targets_do_not_mark_full_map(self):
        # Identical live content in two candidate desktop roots must never be
        # silently selected as a destination for a restore.
        data=self.files["desktop2/AI Cockpit START.lnk"][1]
        (self.desktop2/"AI Cockpit START.lnk").write_bytes(data)
        p=self.scan(save=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("TARGET_AMBIGUOUS=1",p.stdout)
        ids=re.findall(r"(?m)^ENCRYPTED_MAP_ID=([0-9a-f]{32})\s*$",p.stdout)
        self.assertEqual(len(ids),1)
        v=self.verify(ids[0])
        self.assertEqual(v.returncode,0,v.stdout+v.stderr)
        self.assertIn("MAP_INVENTORY_PARTIAL=true",v.stdout)
        self.assertIn("ENCRYPTED_MAP_RECEIPT=VERIFIED_PARTIAL_HOLD",v.stdout)
        self.assert_safe(v)

if __name__=="__main__":
    unittest.main()
