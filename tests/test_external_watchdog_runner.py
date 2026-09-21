import json,tempfile,unittest
from datetime import datetime
from pathlib import Path
from scripts.external_watchdog_runner import run_once
from scripts.local_source_health_contract import validate
class ExternalWatchdogRunnerTests(unittest.TestCase):
 def test_missing_input_fails_closed(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/"out.json"; r=run_once(Path(d)/"missing.json",out,now=datetime.fromisoformat("2026-09-21T09:10:00+09:00"))
   self.assertEqual(r["state"],"UNKNOWN"); self.assertTrue(validate(json.loads(out.read_text(encoding="utf-8"))))
 def test_stale_input_emits_stopped(self):
  with tempfile.TemporaryDirectory() as d:
   inp=Path(d)/"in.json"; out=Path(d)/"out.json"
   inp.write_text(json.dumps({"schema_version":"local-source-health-1.0","source":"KIOXIA_SAFETY_HEARTBEAT","state":"HEALTHY","observed_at":"2026-09-21T09:09:40+09:00","last_data_at":None,"symbol":"TSE:285A","correlation_id":None,"consecutive_failures":0,"reasons":[]}),encoding="utf-8")
   r=run_once(inp,out,now=datetime.fromisoformat("2026-09-21T09:10:00+09:00")); self.assertEqual(r["state"],"STOPPED")
 def test_no_private_payload_fields(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/"out.json"; run_once(Path(d)/"missing.json",out,now=datetime.fromisoformat("2026-09-21T09:10:00+09:00"))
   txt=out.read_text(encoding="utf-8").lower()
   for word in ("order","fill","position","account","board","tape"): self.assertNotIn(word,txt)
