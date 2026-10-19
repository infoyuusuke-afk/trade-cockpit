"""The real Collector payload statement must evaluate on Windows PowerShell 5.1.

2026-10-19 OWNER PC (after hours, candidate 65d6015b): every Collector cycle
crashed at the `$payload=[ordered]@{...}` line with "Argument types do not
match", because `missing_rows=@($missingRows)` wraps a generic List in @()
inside a hashtable literal, which Windows PowerShell 5.1 rejects. The
Collector restarted and crashed again, so live_ms2.json was never written.

This test extracts that exact statement from the shipped Collector and runs
it in powershell.exe 5.1 with synthetic stand-ins for every variable it reads,
with 0 and 2 missing rows. It also scans the V10 PowerShell sources for any
`@($genericList)` inside a hashtable literal. Synthetic values only.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"

HARNESS = r"""
param([string]$Collector)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Collector, [ref]$t, [ref]$e)
if ($e.Count) { throw 'PARSE_FAILED' }
$assign = @($ast.FindAll({ param($n)
    $n -is [Management.Automation.Language.AssignmentStatementAst] -and
    $n.Left.Extent.Text -eq '$payload' -and $n.Right.Extent.Text.Contains('missing_row') }, $true))
if ($assign.Count -ne 1) { throw ('PAYLOAD_STATEMENT_COUNT=' + $assign.Count) }
$names = @($assign[0].Right.FindAll({ param($n) $n -is [Management.Automation.Language.VariableExpressionAst] }, $true) |
    ForEach-Object { $_.VariablePath.UserPath -replace '^script:', '' } |
    Where-Object { $_ -notin @('true', 'false', 'null', '_', 'PSScriptRoot') } | Sort-Object -Unique)
$out = [ordered]@{ ps_major = $PSVersionTable.PSVersion.Major; runs = @() }
foreach ($n in @(0, 2)) {
    foreach ($name in $names) { Set-Variable -Name $name -Value 'synthetic' -Scope Script }
    $script:now = [DateTimeOffset]::new(2026, 10, 19, 17, 13, 0, [TimeSpan]::FromHours(9)).DateTime
    $script:livePriceDiagnostics = [ordered]@{ source_mode = 'MS2_RSS_WORKBOOK'; price_source_status = 'OK' }
    $script:priceSourceMismatch = $false
    $script:publishLiveValues = $false
    $script:validCount = 99
    $script:results = @([pscustomobject]@{ ticker = 'SYN1.T' })
    $script:qualified = @()
    $script:missingRows = New-Object System.Collections.Generic.List[object]
    for ($i = 0; $i -lt $n; $i++) { [void]$script:missingRows.Add([ordered]@{ ticker = ('SYN' + $i + '.T'); reason = 'PRICE_MISSING'; price = $null }) }
    # Lines the Collector runs just before the payload statement (if present).
    $pre = @($ast.FindAll({ param($x)
        $x -is [Management.Automation.Language.AssignmentStatementAst] -and
        $x.Left.Extent.Text -in @('$missingRowArray', '$missingRowCount') }, $true))
    foreach ($p in $pre) { . ([scriptblock]::Create($p.Extent.Text)) }
    try {
        . ([scriptblock]::Create($assign[0].Extent.Text))
        $json = $payload | ConvertTo-Json -Depth 6 -Compress
        $parsed = $json | ConvertFrom-Json
        $out.runs += [ordered]@{ missing = $n; ok = $true; count = $parsed.missing_row_count; rows = @($parsed.missing_rows).Count; error = '' }
    } catch {
        $out.runs += [ordered]@{ missing = $n; ok = $false; count = $null; rows = $null; error = $_.Exception.Message }
    }
}
$out | ConvertTo-Json -Depth 5 -Compress
"""

SCAN = r"""
param([string[]]$Files)
$ErrorActionPreference = 'Stop'
$hits = @()
foreach ($f in $Files) {
    $t = $null; $e = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($f, [ref]$t, [ref]$e)
    $lists = @($ast.FindAll({ param($n)
        $n -is [Management.Automation.Language.AssignmentStatementAst] -and
        $n.Right.Extent.Text -match 'Collections\.Generic\.(List|HashSet)' }, $true) |
        ForEach-Object { ($_.Left.Extent.Text -replace '^\$(script:)?', '') })
    $tables = $ast.FindAll({ param($n) $n -is [Management.Automation.Language.HashtableAst] }, $true)
    foreach ($h in $tables) {
        foreach ($pair in $h.KeyValuePairs) {
            $arr = $pair.Item2.Find({ param($n) $n -is [Management.Automation.Language.ArrayExpressionAst] }, $true)
            if ($null -eq $arr) { continue }
            $vars = @($arr.FindAll({ param($n) $n -is [Management.Automation.Language.VariableExpressionAst] }, $true) |
                ForEach-Object { $_.VariablePath.UserPath -replace '^script:', '' })
            foreach ($v in $vars) { if ($lists -contains $v) { $hits += ($f + ':' + $arr.Extent.StartLineNumber + ':' + $arr.Extent.Text) } }
        }
    }
}
[ordered]@{ hits = @($hits) } | ConvertTo-Json -Compress
"""


def _windows_powershell():
    return shutil.which("powershell")


def _run(script, args):
    exe = _windows_powershell()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "h.ps1"
        path.write_text(script, encoding="utf-8-sig")
        proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path), *args],
                              capture_output=True, timeout=120)
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise AssertionError(out[-2000:] + proc.stderr.decode("utf-8", errors="replace")[-2000:])
    return json.loads(out.splitlines()[-1].lstrip("﻿"))


@unittest.skipIf(_windows_powershell() is None, "Windows PowerShell 5.1 only; the Windows CI job must not skip this")
class CollectorPayloadOnPs51(unittest.TestCase):
    def test_real_payload_statement_builds_with_and_without_missing_rows(self):
        result = _run(HARNESS, ["-Collector", str(COLLECTOR)])
        self.assertEqual(result["ps_major"], 5)
        runs = {r["missing"]: r for r in result["runs"]}
        for n in (0, 2):
            with self.subTest(missing=n):
                self.assertTrue(runs[n]["ok"], runs[n]["error"])
                self.assertEqual(runs[n]["count"], n)
                self.assertEqual(runs[n]["rows"], n)

    def test_no_generic_list_wrapped_in_array_inside_hashtable(self):
        files = [str(p) for p in sorted((ROOT / "ms2_live").glob("*.ps1"))]
        files += [str(p) for p in sorted((ROOT / "downloads").glob("*V10*.ps1"))]
        result = _run(SCAN, ["-Files", *files])
        self.assertEqual(result["hits"] or [], [])


if __name__ == "__main__":
    unittest.main()
