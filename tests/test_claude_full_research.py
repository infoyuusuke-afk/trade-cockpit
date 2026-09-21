import json,tempfile,unittest
from pathlib import Path
from scripts.run_claude_full_research import run
class ClaudeFullResearchTests(unittest.TestCase):
 def payload(self):
  bars=[];p=100.0
  for i in range(240):
   bars.append({"timestamp":f"2026-09-18T{9+(i*15)//3600:02d}:{((i*15)%3600)//60:02d}:{(i*15)%60:02d}+09:00",
    "open":p,"high":p+1,"low":p-1,"close":p+.2,"volume":1000+i});p+=.05
  return {"meta":{"symbol":"TSE:285A","timeframe":"15S","retrieved_at":"2026-09-21T18:00:00+09:00","timezone":"Asia/Tokyo"},"bars":bars}
 def test_one_command_writes_research_evidence_and_never_live(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"claude.json";p.write_text(json.dumps(self.payload()),encoding="utf-8")
   mp,m=run(p,Path(d)/"out",min_train=1,test_size=1)
   self.assertTrue(mp.exists())
   for k in ("calibration","oos","walk_forward","promotion_gate"):self.assertTrue(Path(m[k]).exists())
   gate=json.loads(Path(m["promotion_gate"]).read_text())
   self.assertTrue(gate["research_only"]);self.assertFalse(gate["auto_execute"]);self.assertFalse(gate["direct_live_promotion"])
if __name__=="__main__":unittest.main()
