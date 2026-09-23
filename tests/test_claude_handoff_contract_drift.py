import json,unittest
from pathlib import Path
from scripts.tradingview_mcp_adapter import REQUIRED_META,REQUIRED_BAR,ALLOWED_TOP,ALLOWED_META,ALLOWED_BAR

class ClaudeHandoffContractDriftTests(unittest.TestCase):
 def schema(self):
  return json.loads(Path("data/claude_tradingview_handoff.schema.json").read_text(encoding="utf-8"))
 def test_runtime_shape_matches_machine_schema(self):
  s=self.schema();meta=s["properties"]["meta"];bar=s["properties"]["bars"]["items"]
  self.assertEqual(set(s["required"]),ALLOWED_TOP)
  self.assertEqual(set(s["properties"]),ALLOWED_TOP)
  self.assertEqual(set(meta["required"]),set(REQUIRED_META));self.assertEqual(set(meta["properties"]),ALLOWED_META)
  self.assertEqual(set(bar["required"]),set(REQUIRED_BAR));self.assertEqual(set(bar["properties"]),ALLOWED_BAR)
  self.assertFalse(s["additionalProperties"]);self.assertFalse(meta["additionalProperties"]);self.assertFalse(bar["additionalProperties"])
 def test_schema_identity_matches_handoff_defaults(self):
  s=self.schema();meta=s["properties"]["meta"]["properties"]
  self.assertEqual(meta["symbol"]["const"],"TSE:285A")
  self.assertEqual(meta["timeframe"]["const"],"15S")
  self.assertEqual(meta["timezone"]["const"],"Asia/Tokyo")
 def test_schema_numeric_contract_matches_runtime_numeric_fields(self):
  p=self.schema()["properties"]["bars"]["items"]["properties"]
  for k in ("open","high","low","close","volume"): self.assertEqual(p[k]["type"],"number")
  self.assertEqual(p["volume"]["minimum"],0)
if __name__=="__main__":unittest.main()
