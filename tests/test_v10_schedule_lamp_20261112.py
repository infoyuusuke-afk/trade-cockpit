"""OWNER 2026-11-12 「AIコクピットのステータスランプでおれは状況確認はしたい」: the 定時 lamp."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")


class ScheduleLamp(unittest.TestCase):
    def test_gateway_serves_the_check_only_with_safe_flags(self):
        self.assertIn("function Get-ScheduleWatchView([string]$RuntimeDir) {", GW)
        self.assertIn("$file = Join-Path $RuntimeDir 'schedule_watch_v1.json'", GW)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-schedule-watch-v1' -or $view.real_submit_allowed -ne $false", GW)
        self.assertIn("$item.Length -le 2 -or $item.Length -gt 16384", GW)
        self.assertIn("if ($path -eq '/schedule_watch.json') {", GW)

    def test_lamp_sits_with_brain_and_grok(self):
        self.assertIn("<div id='trade-brain-lamp'></div><div id='trade-ai-lamp'></div><div id='trade-sched-lamp'></div>", HTML)

    def test_lamp_colours(self):
        i = HTML.index("const renderSched=()=>{")
        block = HTML[i:HTML.index("setInterval(renderSched,60000);", i)]
        self.assertIn('fetch("/schedule_watch.json?t="+Date.now(),{cache:"no-store"})', block)
        self.assertIn('h==null||h>limit?["gray","定時：点検が古い"', block)
        self.assertIn("limit=offDay?66:26", block)
        self.assertIn('j.state==="STOPPED"?["red","定時：止まりあり"', block)
        self.assertIn('j.state==="LATE"?["yellow","定時：遅れあり"', block)
        self.assertIn('j.state==="OK"&&j.checked>0?["green","定時：正常"', block)   # audit b8bb448: unknown states are gray
        self.assertIn('["gray","定時：点検が読めない"', block)
        self.assertIn('try{window.cockpitSpeak(stopped?', block)
        self.assertIn('el.title="";', HTML[i:HTML.index("setInterval(renderSched,60000);", i)])
        self.assertNotIn("innerHTML=\"+", block)

    def test_voice_once_per_job_per_day_after_the_stop_loss(self):
        # OWNER 2026-11-12 「あと音声も」「黄か赤に変わった時に1回だけ声で知らせる（同じ定時は1日1回、損切りの声が優先）」
        i = HTML.index("const renderSched=()=>{")
        block = HTML[i:HTML.index("setInterval(renderSched,60000);", i)]
        self.assertIn('if((cls==="red"||cls==="yellow")&&typeof window.cockpitSpeak==="function"){', block)
        self.assertIn("const fresh=probs.filter(p=>p&&p.name&&!mem.names.includes(String(p.name)));", block)
        self.assertIn('localStorage.setItem("cockpitSchedSpokenV2",JSON.stringify(mem))', block)
        self.assertIn("window.__schedSpoken=mem;", block)   # no repeat without storage
        self.assertIn("stopOn=!!(g&&Array.isArray(g.stop)&&g.stop.length);", block)
        self.assertIn("if(fresh.length&&!stopOn){", block)   # the stop-loss voice comes first
        self.assertIn("定時の点検。止まっている定時が", block)
        self.assertNotIn("cockpitSchedSpokenV1", block)

    def test_press_opens_the_list(self):
        # OWNER 2026-11-12 「定時ランプ（緑・黄・赤、押すと一覧）」
        i = HTML.index("const renderSched=()=>{")
        block = HTML[i:HTML.index("setInterval(renderSched,60000);", i)]
        self.assertIn("window.__schedOpen=!window.__schedOpen;renderSched();", block)
        self.assertIn("esc(String(x.name||\"\"))", block)
        self.assertIn("esc(String(x.msg||\"\"))", block)
        self.assertIn(".sched-list{", block)


if __name__ == "__main__":
    unittest.main()
