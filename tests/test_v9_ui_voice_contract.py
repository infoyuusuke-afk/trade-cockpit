from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


class V9UiVoiceContract(unittest.TestCase):
    def test_browser_legacy_tts_removed(self):
        for rel in ("index.html", "scripts/update.py", "voice_client.js"):
            text = read(rel)
            self.assertNotIn("speechSynthesis", text, rel)
            self.assertNotIn("SpeechSynthesisUtterance", text, rel)

    def test_runtime_voice_paths_have_no_windows_sapi(self):
        files = (
            "ms2_live/Kioxia_RSS_Live_Watcher.ps1",
            "ms2_live/Kioxia_Safety_Heartbeat.ps1",
            "ms2_live/MS2_RSS_100_Collector.ps1",
            "ms2_live/SPEAK_TODAY_STRATEGY.ps1",
            "ms2_live/SPEAK_LIVE_EMOTION.ps1",
        )
        for rel in files:
            text = read(rel)
            self.assertNotIn("SAPI.SpVoice", text, rel)
            self.assertIn("28583", text, rel)

    def test_voice_bridge_is_single_sbv2_backend(self):
        text = read("downloads/AI_COCKPIT_VOICE_BRIDGE_V9.ps1")
        self.assertIn("Style-Bert-VITS2", text)
        self.assertIn('ModelName = "amitaro"', text)
        self.assertIn('SpeakerName = "あみたろ"', text)
        self.assertIn("/voice?", text)
        self.assertNotIn("SAPI.SpVoice", text)

    def test_v9_controller_supervises_voice(self):
        text = read("downloads/AI_COCKPIT_CONTROLLER_V9.ps1")
        for needle in (
            "$PORT_VOICE = 28583",
            "voice_bridge_pid",
            "voice_bridge_status",
            "sbv2_status",
            "AI_COCKPIT_VOICE_BRIDGE_V9.ps1",
            "V9_RUNTIME.json",
        ):
            self.assertIn(needle, text)

    def test_v9_runner_deploys_all_runtime_voice_sources(self):
        text = read("downloads/RUN_AI_COCKPIT_V9.ps1")
        for name in (
            "Kioxia_RSS_Live_Watcher.ps1",
            "Kioxia_Safety_Heartbeat.ps1",
            "MS2_RSS_100_Collector.ps1",
            "SPEAK_TODAY_STRATEGY.ps1",
            "SPEAK_LIVE_EMOTION.ps1",
        ):
            self.assertIn(name, text)
        self.assertIn("V9_RUNTIME.json", text)
        self.assertIn("fix/v9-ui-voice-convergence", text)

    def test_gateway_exposes_voice_health(self):
        text = read("downloads/AI_COCKPIT_GATEWAY_V9.ps1")
        for needle in ("voice_bridge_status", "sbv2_status", "voice_backend", "Style-Bert-VITS2"):
            self.assertIn(needle, text)

    def test_all_remaining_tables_have_runtime_card_adapter(self):
        index = read("index.html")
        generator = read("scripts/update.py")
        adapter = read("card_table_adapter.js")
        css = read("card_table_adapter.css")
        for text in (index, generator):
            self.assertIn("card_table_adapter.css", text)
            self.assertIn("card_table_adapter.js", text)
            self.assertIn("voice_client.js", text)
        self.assertIn('querySelectorAll("main table, .tab-pane table, section table")', adapter)
        self.assertIn("cc-data-card", adapter)
        self.assertIn(".cc-table-grid", css)

    def test_only_kioxia_chart_remains(self):
        self.assertEqual(read("index.html").count("LightweightCharts.createChart"), 1)
        self.assertEqual(read("scripts/update.py").count("LightweightCharts.createChart"), 1)
        self.assertNotIn('id="trade-drawer"', read("index.html"))
        self.assertIn('id="kio-best-path"', read("index.html"))

    def test_card_layout_has_responsive_wrap_guards(self):
        css = read("card_table_adapter.css")
        for needle in (
            "minmax(245px,1fr)",
            "-webkit-line-clamp:2",
            "overflow-wrap:anywhere",
            "@media(max-width:640px)",
        ):
            self.assertIn(needle, css)


if __name__ == "__main__":
    unittest.main()
