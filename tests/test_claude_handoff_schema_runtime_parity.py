import json,unittest
from pathlib import Path
from scripts.tradingview_mcp_adapter import REQUIRED_META,REQUIRED_BAR,ALLOWED_TOP,ALLOWED_META,ALLOWED_BAR

SCHEMA=Path("data/claude_tradingview_handoff.schema.json")

class ClaudeHandoffSchemaRuntimeParityTests(unittest.TestCase):
 def schema(self):
  return json.loads(SCHEMA.read_text(encoding="utf-8"))
 def test_allowed_and_required_fields_match_runtime(self):
  s=self.schema();meta=s["properties"]["meta"];bar=s["properties"]["bars"]["items"]
  self.assertEqual(set(s["properties"]),ALLOWED_TOP)
  self.assertEqual(set(s["required"]),ALLOWED_TOP)
  self.assertFalse(s["additionalProperties"])
  self.assertEqual(set(meta["properties"]),ALLOWED_META)
  self.assertEqual(set(meta["required"]),set(REQUIRED_META))
  self.assertFalse(meta["additionalProperties"])
  self.assertEqual(set(bar["properties"]),ALLOWED_BAR)
  self.assertEqual(set(bar["required"]),set(REQUIRED_BAR))
  self.assertFalse(bar["additionalProperties"])
 def test_identity_constants_are_frozen(self):
  meta=self.schema()["properties"]["meta"]["properties"]
  self.assertEqual(meta["symbol"]["const"],"TSE:285A")
  self.assertEqual(meta["timeframe"]["const"],"15S")
  self.assertEqual(meta["timezone"]["const"],"Asia/Tokyo")
 def test_bar_numeric_contract_is_frozen(self):
  props=self.schema()["properties"]["bars"]["items"]["properties"]
  for key in ("open","high","low","close","volume"): self.assertEqual(props[key]["type"],"number")
  self.assertEqual(props["volume"]["minimum"],0)
  self.assertEqual(self.schema()["properties"]["bars"]["minItems"],1)

if __name__=="__main__":unittest.main()
