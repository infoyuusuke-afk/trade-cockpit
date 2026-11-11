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
        self.assertIn('"WATCH"  { return @{length=1.35;weight=0.50;split=0.95} }', BRIDGE)   # OWNER 2026-11-11 「音声がききとりにくい」: slower again
        self.assertIn('"HOT"    { return @{length=1.12;weight=0.70;split=0.50} }', BRIDGE)

    def test_ir_voice_says_the_judgement_in_plain_words(self):
        # OWNER 2026-11-11 「音声 こうより警戒ってなんかわかりにくい」
        self.assertIn('"高寄り警戒・押し目確認"{"あしたは高く始まりそうです。いったん下がるのを待ってから"}', SRC)
        self.assertIn('"急騰過熱・翌朝飛び乗り禁止"{"上がりすぎです。あしたの朝は飛び乗らないでください"}', SRC)
        self.assertIn('"パーセント。"+$irSay+"。")', SRC)
        self.assertNotIn('"パーセント。"+$ir.judgement+"。")', SRC)
        self.assertIn('judgement=$judgement;pts_date=$ptsMatch.pts_date}', SRC)   # the screen and the CSV keep the label

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "no PowerShell")
    def test_bridge_reads_names_for_every_voice(self):
        # OWNER 2026-11-11 「音声がききとりにくい、銘柄名など」: the screen's voices go to the bridge directly, so it reads names too
        start = BRIDGE.index("function U(") if "function U(" in BRIDGE else BRIDGE.index("function Normalize-SpeechText")
        fn = BRIDGE[start:BRIDGE.index("function Get-Profile")]
        text = "ショートリバ上がり切り。HENNGE（4475）。SCREEN HD（7735）、三菱UFJ FG（8306）。"
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.txt"
            ps = Path(d) / "t.ps1"
            # audit 95654e8: the script is written WITHOUT a BOM, as the bridge runs (Windows PowerShell reads it in the system
            # code page); the input text comes from a UTF-8 file so only the function's own characters are read like the bridge's
            src = Path(d) / "in.txt"
            src.write_text(text, encoding="utf-8")
            ps.write_text(fn + "\n$o=Normalize-SpeechText ([IO.File]::ReadAllText('%s',[Text.Encoding]::UTF8))\n[IO.File]::WriteAllText('%s',$o,[Text.UTF8Encoding]::new($false))\n"
                          % (src, out), encoding="utf-8")
            exe = shutil.which("powershell") or shutil.which("pwsh")
            subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], capture_output=True, timeout=120)
            got = out.read_text(encoding="utf-8")
        # OWNER 2026-11-11 「コードもよんで」: the code is read one character at a time after the name
        self.assertEqual(got, "ショートリバ上がり切り。ヘンゲ,コード よん よん なな ご。スクリーン ホールディングス,コード なな なな さん ご、"
                              "三菱ユーエフジェイ フィナンシャルグループ,コード はち さん ぜろ ろく。")
        self.assertTrue(all(ord(c) < 128 for c in fn.split("\n")[0]))
        self.assertNotIn("（", fn)   # no raw full-width bracket in the bridge's code (it would be garbled under cp932)

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
        # OWNER 2026-11-11 「コードもよんで」: the code is read one character at a time after the name (it was dropped on 11/02)
        self.assertEqual(got, "きおくしあ ホールディングス、コード に はち ご エー、マイナス15パーセント。スクリーン ホールディングス、コード なな なな さん ご、マイナス12パーセント。"
                              "コクサイ エレクトリック、コード ろく ご に ご、マイナス10パーセント。三井住友フィナンシャルグループ、コード はち さん いち ろく。ティアフォー、コード ご きゅう さん エー。")


if __name__ == "__main__":
    unittest.main()
