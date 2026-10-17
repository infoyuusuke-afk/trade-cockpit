"""P0-32 clean-path immutable-surface audit.

Independent *mechanical* contract for the reviewer-unavailable case; this is
not a second person's code review. No Windows/OWNER actions or network usage.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "downloads" / "VERIFY_V10_LEGACY_OWNER_READONLY_V1.ps1"
V2 = ROOT / "downloads" / "VERIFY_V10_LEGACY_OWNER_READONLY_V2.ps1"
ORIGINAL = "P0-27: one non-stopping OWNER entry for the legacy V10 session."
REPLACED = "P0-32: independent metadata-only-safe diagnostic for legacy V10, derived from P0-27."
GATE_V1 = 'foreach($k in @("STATE_UNCHANGED","ROOT_RESULT_AND_EVIDENCE_UNCHANGED"'
GATE_V2 = "# P0-32: independent read-only outcome"
SUFFIX = "}catch{"


def audit_surface(v1, v2):
    """Fail if V2 changes any executable region beyond the reviewed gate."""
    assert v1.count(ORIGINAL) == 1, "original signature"
    assert v2.count(REPLACED) == 1, "new signature"
    assert v1.count(GATE_V1) == 1, "old gate"
    assert v2.count(GATE_V2) == 1, "new gate"
    i1 = v1.index(GATE_V1)
    i2 = v2.index(GATE_V2)
    j1 = v1.index(SUFFIX, i1)
    j2 = v2.index(SUFFIX, i2)
    assert v1[:i1].replace(ORIGINAL, REPLACED) == v2[:i2], "preflight changed"
    assert v1[j1:] == v2[j2:], "catch/cleanup/safety report changed"
    gate = v2[i2:j2]
    # New success classification must be distinct and never hide old false.
    for token in (
        'if($counts.STATE_CHANGE_CLASS -ceq "METADATA_ONLY" -and -not $IncludeStopDryRun)',
        '$recheck=Get-Fingerprint $rootFull',
        '$before.StateHash -cne "ABSENT"',
        '$after.StateHash -ceq $before.StateHash',
        '$recheck.StateHash -ceq $before.StateHash',
        '$recheck.Result -ceq $before.Result',
        '$recheck.Evidence -ceq $before.Evidence',
        '$recheck.Excel -ceq $before.Excel',
        '$recheck.Listen -ceq $before.Listen',
        '$recheck.Launch -ceq $before.Launch',
        '$recheck.DryRunDirs -ceq $before.DryRunDirs',
        '$after.DryRunDirs -ceq $before.DryRunDirs',
        '@($entries | Where-Object { -not (Test-EntryAlive $_) }).Count -eq 0',
        'if($counts.STATE_UNCHANGED -cne "true" -and -not $metadataAdmitted)',
        '$result=if($metadataAdmitted){"READONLY_METADATA_STABLE"}',
        'if($counts[$k] -cne "true"){Block ("CHANGED_DURING_CHECK_"+$k)}',
        'if($counts.STOP_DRY_RUN_TEMP_LEFT -cne "false"){Block "STOP_DRY_RUN_TEMP_LEFT"}',
    ):
        assert token in gate, "missing V2 proof: " + token
    for prohibited in (
        'Stop-Process', 'Start-Process', 'Stop-Service', 'Set-Content',
        'Move-Item', 'Rename-Item', 'taskkill', '-ComObject', '.Kill(',
        'Invoke-Expression', '[ScriptBlock]::Create', 'Start-Job',
    ):
        assert prohibited not in gate, "prohibited in new executable gate: " + prohibited
    assert v1.count('Write-Output "STOP_ALLOWED=false"') == 1
    assert v2.count('Write-Output "STOP_ALLOWED=false"') == 1
    assert v1.count('Write-Output "CUTOVER_ELIGIBLE=false"') == 1
    assert v2.count('Write-Output "CUTOVER_ELIGIBLE=false"') == 1
    assert v1.count('Write-Output "REAL_SUBMIT_ALLOWED=false"') == 1
    assert v2.count('Write-Output "REAL_SUBMIT_ALLOWED=false"') == 1


class V2SafetyContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v1 = V1.read_text(encoding="utf-8")
        cls.v2 = V2.read_text(encoding="utf-8")

    def test_only_documented_gate_changed(self):
        audit_surface(self.v1, self.v2)

    def test_tampered_stop_permission_rejected(self):
        tampered = self.v2.replace('Write-Output "STOP_ALLOWED=false"',
                                   'Write-Output "STOP_ALLOWED=true"', 1)
        with self.assertRaises(AssertionError):
            audit_surface(self.v1, tampered)

    def test_tampered_preflight_rejected(self):
        tampered = self.v2.replace('$stage="ADMISSION"',
                                   '$stage="ADMISSION";Start-Process bogus', 1)
        with self.assertRaises(AssertionError):
            audit_surface(self.v1, tampered)

    def test_removed_third_state_hash_proof_rejected(self):
        tampered = self.v2.replace('$recheck.StateHash -ceq $before.StateHash',
                                   '$recheck.StateHash -cne "ABSENT"', 1)
        with self.assertRaises(AssertionError):
            audit_surface(self.v1, tampered)

    def test_result_cannot_reclassify_stop_dry_run_as_pass(self):
        tampered = self.v2.replace(
            'if($counts.STATE_CHANGE_CLASS -ceq "METADATA_ONLY" -and -not $IncludeStopDryRun)',
            'if($counts.STATE_CHANGE_CLASS -ceq "METADATA_ONLY")', 1)
        with self.assertRaises(AssertionError):
            audit_surface(self.v1, tampered)


if __name__ == "__main__":
    unittest.main()
