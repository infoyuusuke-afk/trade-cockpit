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
        # OWNER 2026-11-14 「改行位置がよみにくい」: one problem on each line, the shared day said once
        self.assertIn(r'.join("\n")+(probs.length>3?"\n・ほか"+(probs.length-3)+"件は、押すと一覧":"")', block)
        self.assertIn('head=probs.length+"件"+(pday?"（前の営業日"+pday+"の分）":"")', block)
        self.assertIn(r'["red","定時：止まりあり",head+"　点検 "+at+"\n"+rows]', block)
        self.assertIn("el.title=(probs.length?allNames:line)", block)   # every name stays in the tooltip and the list
        self.assertIn("#trade-sched-lamp{position:relative;min-width:0;max-width:100%}#trade-sched-lamp .brain-lamp small{white-space:pre-line!important;overflow-wrap:break-word;line-height:1.6}", HTML)


class LinesBreakBetweenPhrases(unittest.TestCase):
    def test_japanese_breaks_between_phrases_and_nothing_runs_out(self):
        # OWNER 2026-11-14 「全タブの文字を全部確認しておかしな箇所は全て修正」: 一|覧, 出|来高 and the like no longer split
        self.assertIn('<html lang="ja">', HTML)
        self.assertIn("body{word-break:auto-phrase;overflow-wrap:break-word}body .cc-data-metric b{word-break:auto-phrase}", HTML)
        self.assertIn("#kioxia-5m-calendar .kio-summary{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}", HTML)
        self.assertIn("#kioxia-5m-calendar .kio-ms2-title strong{white-space:normal!important;max-width:100%}", HTML)


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
