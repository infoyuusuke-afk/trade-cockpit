import json, unittest
from pathlib import Path
from scripts import event_bus
ROOT=Path(__file__).resolve().parents[1]
class AIContractTests(unittest.TestCase):
 def test_event_schema_version_matches_runtime(self):
  schema=json.loads((ROOT/"data/cockpit_event.schema.json").read_text())
  self.assertEqual(schema["properties"]["schema_version"]["const"],event_bus.SCHEMA_VERSION)
  self.assertEqual(schema["properties"]["real_submit_allowed"]["const"],False)
  self.assertEqual(schema["properties"]["external_publish_allowed"]["const"],False)
 def test_org_keeps_owner_gates(self):
  org=json.loads((ROOT/"config/ai_organization_v1.json").read_text())
  self.assertEqual(set(org["owner_approval_required_for"]),{"main_merge","real_money_submit","external_publish"})
  self.assertFalse(org["defaults"]["real_submit_allowed"]); self.assertFalse(org["defaults"]["external_publish_allowed"])
  risk=next(r for r in org["roles"] if r["id"]=="RISK"); self.assertTrue(risk["veto"])
