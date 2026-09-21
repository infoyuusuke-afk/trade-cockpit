import unittest
from scripts import event_bus as eb
from scripts import ai_council as council
from scripts import owner_command_center as cc
from scripts import journal_projection as jp
from scripts import commentary_scheduler as cs
from scripts import storyboard_generator as sg
def ev(domain="SYSTEM",severity="INFO",event_type="DEVELOPMENT_MILESTONE",sec=0,payload=None):
 return eb.build_event(timestamp=f"2026-09-21T21:00:{sec:02d}+09:00",domain=domain,event_type=event_type,source="test",severity=severity,payload=payload or {"summary":"x"})
class ProjectionTests(unittest.TestCase):
 def test_command_center_surfaces_critical_and_owner_queue(self):
  a=ev(severity="CRITICAL",payload={"summary":"stale","owner_approval_required":True})
  snap=cc.build_command_center([a],{"status":"BLOCK"})
  self.assertEqual(snap["system_status"],"ATTENTION"); self.assertEqual(snap["pending_owner_approvals"],1); self.assertEqual(snap["council_status"],"BLOCK"); self.assertFalse(snap["real_submit_allowed"])
 def test_journal_is_projection_and_ordered(self):
  a=ev(domain="RISK",sec=2,payload={"summary":"risk","decision":"BLOCK"}); b=ev(domain="MARKET",sec=1,payload={"summary":"move"})
  before=dict(a); rows=jp.journal_rows([a,b])
  self.assertEqual([r["summary"] for r in rows],["move","risk"]); self.assertEqual(a,before)
 def test_commentary_cooldown(self):
  xs=[{"event_id":"a","priority":1,"timestamp":"2026-09-21T21:00:10+09:00","text":"a","speech_text":"a"},{"event_id":"b","priority":2,"timestamp":"2026-09-21T21:00:25+09:00","text":"b","speech_text":"b"},{"event_id":"c","priority":3,"timestamp":"2026-09-21T21:00:35+09:00","text":"c","speech_text":"c"}]
  out=cs.schedule(xs,cooldown_seconds=20,max_items=2); self.assertEqual([x["event_id"] for x in out],["a","c"])
 def test_storyboard_never_publishes(self):
  c={"event_id":"x","title_seed":"勝負","external_publish_allowed":False}
  x=sg.storyboard(c,{"context":"寄り","conflict":"AI対立","lesson":"見送り"})
  self.assertEqual(len(x["scenes"]),3); self.assertEqual(x["status"],"DRAFT_INTERNAL"); self.assertFalse(x["external_publish_allowed"]); self.assertTrue(x["owner_approval_required"])
