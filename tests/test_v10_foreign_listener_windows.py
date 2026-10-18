"""AST-extracted production Controller foreign-port preflight, no real listener.

Run only in disposable Windows GitHub Actions. Mock the OS listener inventory,
including IPv6-only foreign bindings and unreadable inventories. Never start
the Controller, Excel, MS2 or any trading component.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parents[1] / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows"
    and shutil.which("powershell.exe"),
    "Windows hosted synthetic-only",
)
class ForeignListenerPreflight(unittest.TestCase):
    def test_all_address_listener_discovery_and_fail_closed_inventory(self):
        script = r'''
param([string]$Source)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'CONTROLLER_PARSE_ERROR'}
$defs=@($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Test-ForeignSession'
},$true))
if($defs.Count -ne 1){throw 'FOREIGN_LISTENER_FUNCTION_NOT_UNIQUE'}
. ([scriptblock]::Create($defs[0].Extent.Text))
$script:PortCollector=28580
$PORT_COLLECTOR=28580
$PORT_GATEWAY=28581
$PORT_WATCHER=28582
$PORT_VOICE=28583
$PORT_BRAIN=28584
$script:Connections=@()
$script:InventoryDenied=$false
$script:Attempts=0
function Get-NetTCPConnection {
    param([string]$State)
    $script:Attempts++
    if($script:InventoryDenied){throw 'CIM_NETTCP_DENIED'}
    return $script:Connections
}
function Get-Process {
    param([int]$Id)
    return [pscustomobject]@{ProcessName='SyntheticUnrelated'}
}
function Test-Port { throw 'UNSAFE_PORT_CONNECT_DEPENDENCY' }
$checks=0
$owned=@{ collector=12345;gateway=0;watcher=0;voice=0;brain=0 }
function Set-Synthetic([string]$Address,[int]$Port,[int]$Owner) {
    $script:Connections=@([pscustomobject]@{
        LocalAddress=$Address;LocalPort=$Port;OwningProcess=$Owner
    })
}
Set-Synthetic '::1' 28580 98765
$r=@(Test-ForeignSession $owned)
if($r.Count -ne 1 -or $r[0] -notmatch '98765' -or $r[0] -notmatch '::1'){
    throw 'IPV6_FOREIGN_LISTENER_NOT_BLOCKED'
}
$checks++
Set-Synthetic '0.0.0.0' 28584 54321
$r=@(Test-ForeignSession $owned)
if($r.Count -ne 1 -or $r[0] -notmatch '54321'){
    throw 'WILDCARD_LISTENER_NOT_BLOCKED'
}
$checks++
Set-Synthetic '127.0.0.1' 28582 98765
$r=@(Test-ForeignSession $owned)
if($r.Count -ne 1){throw 'LOOPBACK_FOREIGN_LISTENER_NOT_BLOCKED'}
$checks++
Set-Synthetic '::' 28580 12345
$r=@(Test-ForeignSession $owned)
if($r.Count -ne 0){throw 'OWNED_LISTENER_REJECTED'}
$checks++
Set-Synthetic '::1' 29999 98765
$r=@(Test-ForeignSession $owned)
if($r.Count -ne 0){throw 'IRRELEVANT_LISTENER_REJECTED'}
$checks++
$script:Connections=@()
$r=@(Test-ForeignSession $owned)
if($r.Count -ne 0){throw 'EMPTY_LISTENER_INVENTORY_REJECTED'}
$checks++
$script:InventoryDenied=$true
$r=@(Test-ForeignSession $owned)
if($r.Count -ne 1 -or $r[0] -notmatch 'LISTENER_INVENTORY_UNKNOWN'){
    throw 'UNREADABLE_LISTENER_INVENTORY_ALLOWED'
}
$checks++
$script:InventoryDenied=$false
Set-Synthetic '::1' 28581 0
$r=@(Test-ForeignSession $owned)
if($r.Count -ne 1 -or $r[0] -notmatch 'unknown listener owner'){
    throw 'UNKNOWN_OWNER_ALLOWED'
}
$checks++
if($script:Attempts -ne $checks){throw 'INVENTORY_NOT_QUERIED_EXACTLY_ONCE'}
Write-Output ('V10_FOREIGN_LISTENER_CASES_PASS='+$checks)
'''
        with tempfile.TemporaryDirectory(prefix="v10-foreign-listener-") as temp:
            harness = Path(temp) / "harness.ps1"
            harness.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(harness), str(CONTROLLER)],
                capture_output=True, text=True, errors="replace", timeout=45,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("V10_FOREIGN_LISTENER_CASES_PASS=8", result.stdout)


if __name__ == "__main__":
    unittest.main()
