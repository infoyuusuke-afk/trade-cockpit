"""P0-29: Collector encoded initializer exact admission vs tampering."""
import os,subprocess,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_v10_legacy_safe_stop as tsl
REPO=Path(__file__).resolve().parents[1]
PREFLIGHT=REPO/"downloads"/"PREFLIGHT_V10_LEGACY_SHUTDOWN_V1.ps1"
WIN=os.name=="nt" and os.environ.get("GITHUB_ACTIONS")=="true" and os.environ.get("RUNNER_OS")=="Windows"
COLLECTOR= r"""param([int]$Port,[string]$Mark)
function Get-NormalizedLocalWorkbookPath { param($p) return $p }
function Get-CollectorFileIdentityType { return 'fixture' }
function Test-SameCanonicalWorkbookFile { param($a,$b) return ($a -eq $b) }
function Get-PublishedWorkbookGate { return '' }
$names=@("Get-NormalizedLocalWorkbookPath","Get-CollectorFileIdentityType","Test-SameCanonicalWorkbookFile","Get-PublishedWorkbookGate")
$text=""
foreach($name in $names) {
 $body=(Get-Item ("function:" + $name)).ScriptBlock.ToString()
 $text+="function "+$name+" {<BT>r<BT>n"+$body+"<BT>r<BT>n}<BT>r<BT>n"
}
$init=[scriptblock]::Create($text)
$j=Start-Job -Name ("MS2_JSON_BRIDGE_" + $PID) -InitializationScript $init -ArgumentList $Port -ScriptBlock {
 param($p)
 $l=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$p)
 $l.Start()
 Start-Sleep -Seconds 300
}
Start-Sleep -Seconds 300
""".replace("<BT>",chr(96))
TAMPER=COLLECTOR.replace('$init=[scriptblock]::Create($text)',
                        '$init=[scriptblock]::Create("Write-Output 123; "+$text)')

class Static(unittest.TestCase):
 def test_exact_initialization_contract(self):
  s=PREFLIGHT.read_text(encoding="utf-8")
  for token in ("Test-CollectorEncodedInitJob","Get-PublishedWorkbookGate",
                "[Convert]::FromBase64String","PORT_CHILD_IDENTITY_NOT_PROVEN"):
   self.assertIn(token,s)
  self.assertNotIn("Invoke-Expression",s)

@unittest.skipUnless(WIN,"Windows synthetic runner only")
class Admissions(tsl.LegacySessionSafeStop):
 def check(self):
  x=subprocess.run([tsl.PS,"-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass",
     "-File",str(PREFLIGHT),"-Root",str(self.root),
     "-AdmissionOut",str(self.root/"admission-p029.json")],
     capture_output=True,text=True,errors="replace",timeout=120)
  print("--- P0-29",self._testMethodName,x.returncode,x.stdout,x.stderr[-300:])
  self.assertNotIn(str(self.root),x.stdout)
  self.assertTrue(tsl.alive(self.excel_managed))
  self.assertTrue(tsl.alive(self.excel_business))
  self.assertTrue(tsl.alive(self.foreign_py))
  return x
 def test_01_identical_initialized_job_allowed_readonly(self):
  (self.runtime/"MS2_RSS_100_Collector.ps1").write_text(COLLECTOR,encoding="ascii")
  self.start_session()
  before=self.state_path.read_bytes()
  r=self.check()
  self.assertEqual(r.returncode,0,r.stdout)
  self.assertIn("PREFLIGHT_RESULT=EVIDENCE_ONLY_PASS",r.stdout)
  self.assertEqual(before,self.state_path.read_bytes())
  self.assert_nothing_stopped()
 def test_02_unapproved_encoded_initializer_blocked(self):
  (self.runtime/"MS2_RSS_100_Collector.ps1").write_text(TAMPER,encoding="ascii")
  self.start_session()
  r=self.check()
  self.assertEqual(r.returncode,2,r.stdout)
  self.assertIn("PREFLIGHT_BLOCK_REASON=PORT_CHILD_IDENTITY_NOT_PROVEN",r.stdout)
  self.assert_nothing_stopped()
 def test_03_normal_start_job_still_works(self):
  self.start_session()
  r=self.check()
  self.assertEqual(r.returncode,0,r.stdout)
  self.assertIn("PREFLIGHT_RESULT=EVIDENCE_ONLY_PASS",r.stdout)
  self.assert_nothing_stopped()
for _name in dir(tsl.LegacySessionSafeStop):
 if _name.startswith("test_"):setattr(Admissions,_name,None)
if __name__=="__main__":unittest.main()
