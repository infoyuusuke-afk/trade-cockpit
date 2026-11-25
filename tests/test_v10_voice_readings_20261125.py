"""OWNER 2026-11-25 「音声で『買いの札』を『さつ』と読んでいる。読み上げの時だけ『札』を『こうほ』に置きかえる版を作って。
画面の文字は変えない。ほかにも読み間違えそうな言葉がないか、音声の文を全部見て」.

The bridge's Normalize-SpeechText is the one place every voice passes through, so the reading-only replacements live there.
Each replacement was checked with the same pyopenjtalk + user dictionary the voice engine uses.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
BRIDGE = (ROOT / "downloads" / "AI_COCKPIT_VOICE_BRIDGE_V10.ps1").read_text(encoding="utf-8-sig")


def u(s):
    return "(U @(" + ",".join(str(ord(c)) for c in s) + "))"


READINGS = [("札", "こうほ"), ("下抜け", "したぬけ"), ("上抜け", "うえぬけ"), ("成行き", "なりゆき"), ("成行", "なりゆき"),
            ("高寄り", "たかより"), ("特売り", "とくうり"), ("前場", "ぜんば"), ("大陽線", "だいようせん"),
            ("売り長", "うりなが"), ("買い長", "かいなが"),
            ("ぶいわっぷの上", "ぶいわっぷのうえ"), ("ぶいわっぷの下", "ぶいわっぷのした"),
            ("ぶいわっぷ上", "ぶいわっぷ、うえ"), ("ぶいわっぷ下", "ぶいわっぷ、した")]


class VoiceReadings(unittest.TestCase):
    def test_bridge_has_every_reading_pair_in_ascii(self):
        fn = BRIDGE[BRIDGE.index("function Normalize-SpeechText"):BRIDGE.index("function Get-Profile")]
        for a, b in READINGS:
            self.assertIn("@(%s,%s)" % (u(a), u(b)), fn)
        self.assertTrue(all(ord(c) < 128 for c in fn))   # the bridge runs under the system code page
        self.assertIn('"8"=(U @(12495,12481))', fn)       # the code's 8 is katakana (hiragana was spoken "wachi")
        self.assertNotIn('"8"=(U @(12399,12385))', fn)
        self.assertIn('"8"="ハチ"', SRC)

    def test_longer_words_are_replaced_before_shorter_ones(self):
        fn = BRIDGE[BRIDGE.index("function Normalize-SpeechText"):BRIDGE.index("function Get-Profile")]
        self.assertLess(fn.index(u("成行き")), fn.index("@(" + u("成行") + ","))
        self.assertLess(fn.index(u("ぶいわっぷの上")), fn.index("@(" + u("ぶいわっぷ上") + ","))

    def test_screen_text_is_not_changed(self):
        # the badge and the screen keep 札; only the voice is read differently
        self.assertIn("札", SRC)
        self.assertNotIn("こうほ", SRC)

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "no PowerShell")
    def test_bridge_reads_the_sentences(self):
        start = BRIDGE.index("function U(") if "function U(" in BRIDGE else BRIDGE.index("function Normalize-SpeechText")
        fn = BRIDGE[start:BRIDGE.index("function Get-Profile")]
        text = ("PTSで買いの札が出ました。OR15下抜け、ぶいわっぷ下。ぶいわっぷの上。成行偏り、成行きで。"
                "高寄り警戒・特売り・前場・大陽線・売り長・買い長。キオクシア（285A）。")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "in.txt"
            out = Path(d) / "o.txt"
            ps = Path(d) / "t.ps1"
            src.write_text(text, encoding="utf-8")
            ps.write_text(fn + "\n$o=Normalize-SpeechText ([IO.File]::ReadAllText('%s',[Text.Encoding]::UTF8))\n[IO.File]::WriteAllText('%s',$o,[Text.UTF8Encoding]::new($false))\n"
                          % (src, out), encoding="utf-8")
            exe = shutil.which("powershell") or shutil.which("pwsh")
            subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], capture_output=True, timeout=120)
            got = out.read_text(encoding="utf-8")
        self.assertEqual(got, "PTSで買いのこうほが出ました。おーあーる、じゅうごしたぬけ、ぶいわっぷ、した。ぶいわっぷのうえ。なりゆき偏り、なりゆきで。"
                              "たかより警戒・とくうり・ぜんば・だいようせん・うりなが・かいなが。きおくしあ,コード に ハチ ご エー。")


if __name__ == "__main__":
    unittest.main()
