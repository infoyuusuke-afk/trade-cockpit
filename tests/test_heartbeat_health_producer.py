import pathlib, unittest
class HeartbeatHealthProducerContractTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.text=pathlib.Path("ms2_live/Kioxia_Safety_Heartbeat.ps1").read_text(encoding="utf-8-sig")
 def test_contract_version_and_local_runtime_path(self):
  self.assertIn('local-source-health-1.0',self.text); self.assertIn('runtime\\heartbeat_source_health.json',self.text)
 def test_atomic_temp_write(self):
  self.assertIn('$healthStatePath + ".tmp"',self.text); self.assertIn('Move-Item -LiteralPath $tmp -Destination $healthStatePath -Force',self.text)
 def test_health_mapping(self):
  self.assertIn('{ "STOPPED" } else { "DEGRADED" }',self.text); self.assertIn('Write-LocalSourceHealth "HEALTHY" 0 @()',self.text)
 def test_no_private_payload_fields_in_health_object(self):
  block=self.text.split('$obj = [ordered]@{',1)[1].split('}',1)[0]
  for forbidden in ("position","order","fill","board","tape","account","歩み値","板"):
   self.assertNotIn(forbidden.lower(),block.lower())
