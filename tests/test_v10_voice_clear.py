"""OWNER 2026-11-02 「8時56分の音声が聞きとれない、はっきりしゃべらせて」."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
BRIDGE = (ROOT / "downloads" / "AI_COCKPIT_VOICE_BRIDGE_V10.ps1").read_text(encoding="utf-8-sig")


class VoiceClear(unittest.TestCase):
    def test_gap_voice_reads_whole_percentages(self):
        self.assertIn('[Math]::Round([double]$_.preopen_gap_pct,0))+"パーセント"', SRC)
        self.assertIn('[Math]::Round($_.gap,0))+"パーセントで"', SRC)
        self.assertNotIn('[Math]::Round([double]$_.preopen_gap_pct,1))', SRC)

    def test_bridge_watch_voice_is_slower_with_longer_pauses(self):
        self.assertIn('"WATCH"  { return @{length=1.25;weight=0.50;split=0.80} }', BRIDGE)

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "no PowerShell")
    def test_names_are_read_without_codes_and_english_in_katakana(self):
        fn = SRC[SRC.index("$script:SpeechNameReadings = @("):SRC.index("function Split-CockpitSpeechText")]
        text = ("キオクシアHD（285A）、マイナス15パーセント。SCREEN HD（7735）、マイナス12パーセント。"
                "KOKUSAI ELECTRIC（6525）、マイナス10パーセント。三井住友FG（8316）。ティアフォー（593A）。")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.txt"
            ps = Path(d) / "t.ps1"
            ps.write_text(fn + "\n$o=Convert-ToCockpitSpeechText '%s'\n[IO.File]::WriteAllText('%s',$o,[Text.UTF8Encoding]::new($false))\n"
                          % (text, out), encoding="utf-8-sig")
            exe = shutil.which("pwsh") or shutil.which("powershell")
            subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], capture_output=True, timeout=120)
            got = out.read_text(encoding="utf-8")
        self.assertEqual(got, "きおくしあ ホールディングス、マイナス15パーセント。スクリーン ホールディングス、マイナス12パーセント。"
                              "コクサイ エレクトリック、マイナス10パーセント。三井住友フィナンシャルグループ。ティアフォー。")


if __name__ == "__main__":
    unittest.main()
