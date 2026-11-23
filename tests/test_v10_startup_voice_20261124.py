"""OWNER 2026-11-24 「起動したの音声がまずでない」: the startup voice is retried while the voice engine is still loading."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"


class StartupVoice(unittest.TestCase):
    def test_retried_inside_the_loop(self):
        t = COLLECTOR.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        self.assertIn("function Invoke-StartupVoiceIfPending {", t)
        self.assertIn("$script:startupVoiceUntil = (Get-Date).AddMinutes(4)", t)
        self.assertIn("$script:startupVoiceNext = $now.AddSeconds(10)", t)
        self.assertIn("if ($script:lastSpeakOk -eq $true) { $script:startupVoicePending = $false; return }", t)
        i = t.index("try {\n    while ($true) {\n")
        self.assertTrue(t[i:i + 120].rstrip().endswith("Invoke-StartupVoiceIfPending"))
        self.assertEqual(t.count('"キオクシアを含む、100銘柄の音声監視を開始しました。"'), 1)


if __name__ == "__main__":
    unittest.main()
