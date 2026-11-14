"""OWNER 2026-11-14 「文字がはみだしている、もう一回全てのタブ、機能が正常なのか時間をかけて丁寧に確認しろ、直ってなければ修正しろ」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class ScheduleLampFits(unittest.TestCase):
    def test_line_names_three_and_wraps(self):
        i = HTML.index("const renderSched=()=>{")
        block = HTML[i:HTML.index("if((cls===\"red\"||cls===\"yellow\")", i)]
        self.assertIn('probs.slice(0,3)', block)
        self.assertIn('"／ほか"+(probs.length-3)+"件（押すと一覧）"', block)
        self.assertIn("el.title=(probs.length?allNames:line)", block)   # every name stays in the tooltip and the list
        self.assertIn("#trade-sched-lamp{position:relative;min-width:0;max-width:100%}#trade-sched-lamp .brain-lamp small{white-space:normal!important;overflow-wrap:anywhere}", HTML)


class StaleLiveFocusDoesNotMuteThePage(unittest.TestCase):
    def test_only_a_fresh_file_of_today_turns_voices_off(self):
        i = HTML.index("const liveFresh=d=>{")
        block = HTML[i:HTML.index("loadLive();setInterval(loadLive,60000);", i)]
        self.assertIn("if(m[1]!==j.slice(0,10))return false;", block)
        self.assertIn("return late>=0&&late<=15;", block)
        self.assertIn("const speak=liveFresh(d)?d.speech_enabled===true:true;", block)
        self.assertIn("window.cockpitVoiceSetLiveEnabled?.(speak);", block)
        self.assertNotIn("window.cockpitLiveSpeechEnabled=d.speech_enabled===true;", HTML)


if __name__ == "__main__":
    unittest.main()
