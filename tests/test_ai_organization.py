import unittest
from scripts import ai_council as c
from scripts import event_bus as e
from scripts import live_commentary as lc
from scripts import entertainment_pipeline as ep
from scripts import project_progress as pp
class OrganizationTests(unittest.TestCase):
 def test_risk_block_wins_and_never_executes(self):
  msgs=[{"agent":"Strategy","topic":"285A","stance":"PROPOSE","proposal":"LONG","evidence":["EV"],"confidence":.7,"risk":"","timestamp":"2026-09-21T09:10:00+09:00"},{"agent":"Risk","topic":"285A","stance":"BLOCK","proposal":None,"evidence":["STALE"],"confidence":1.0,"risk":"STALE","timestamp":"2026-09-21T09:10:01+09:00"}]
  x=c.council_snapshot(msgs); self.assertEqual(x["status"],"BLOCK"); self.assertFalse(x["real_submit_allowed"]); self.assertTrue(x["owner_approval_required"])
 def test_commentary_priority_and_dedupe(self):
  def ev(sev,text,sec):
   return e.build_event(timestamp=f"2026-09-21T09:10:{sec:02d}+09:00",domain="COMMENTARY",event_type="MARKET_NOTE",source="Commentary",severity=sev,payload={"summary":text})
  out=lc.select_commentary([ev("INFO","same",1),ev("CRITICAL","urgent",2),ev("NOTICE","same",3)])
  self.assertEqual(out[0]["text"],"urgent"); self.assertEqual(sum(x["text"]=="same" for x in out),1)
 def test_entertainment_is_draft_only(self):
  x=e.build_event(timestamp="2026-09-21T21:00:00+09:00",domain="SYSTEM",event_type="DEVELOPMENT_MILESTONE",source="ChatGPT",payload={"summary":"827 tests pass"})
  from scripts.content_sanitizer import sanitize_event
        cs=ep.story_candidates([sanitize_event(x)]); self.assertEqual(len(cs),1)
  p=ep.publishing_package(cs[0]); self.assertEqual(p["status"],"DRAFT_INTERNAL"); self.assertFalse(p["external_publish_allowed"]); self.assertTrue(p["owner_approval_required"])
 def test_progress(self):
  self.assertEqual(pp.summarize([{"progress":50,"status":"進行中"},{"progress":100,"status":"完了"},{"progress":0,"status":"Blocked"}]),{"overall_progress":50.0,"blocked":1,"open":2})
