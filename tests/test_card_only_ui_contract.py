import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
UPDATE = (ROOT / "scripts" / "update.py").read_text(encoding="utf-8")
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "downloads" / "START_AI_COCKPIT_V6.ps1").read_text(encoding="utf-8-sig")
GATEWAY = (ROOT / "downloads" / "AI_Cockpit_Local_Gateway.ps1").read_text(encoding="utf-8-sig")


class CardOnlyUiContractTests(unittest.TestCase):
    def test_all_legacy_tables_are_cardified(self):
        for source in (UPDATE, INDEX):
            self.assertIn("cockpit-card-unifier-style", source)
            self.assertIn('document.querySelectorAll("table").forEach(observeTable)', source)
            self.assertIn("legacy-table-cardified", source)
            self.assertIn("table-card-grid", source)
            self.assertIn("unified-data-card", source)
            self.assertIn("MutationObserver", source)

    def test_dynamic_table_updates_remain_cards(self):
        self.assertIn('new MutationObserver(() => renderTable(table)).observe(table', UPDATE)
        self.assertIn('new MutationObserver(() => renderTable(table)).observe(table', INDEX)
        self.assertIn("characterData:true", INDEX)

    def test_only_non_kioxia_top5_chart_is_removed_from_card_mode(self):
        self.assertIn("body.cards-only .focus-chart-wrap{display:none!important}", UPDATE)
        self.assertIn("body.cards-only .focus-chart-wrap{display:none!important}", INDEX)
        self.assertIn('id="kioxia-5m-calendar"', INDEX)
        self.assertNotIn("body.cards-only #kioxia-5m-calendar{display:none", INDEX)

    def test_fix_channel_serves_fix_branch_ui(self):
        self.assertIn('V6_INSTALL_CHANNEL.txt', LAUNCHER)
        self.assertIn('refs/heads/fix/live-session-state-v1', LAUNCHER)
        self.assertIn('-RemoteBase "', LAUNCHER)
        self.assertIn("$cockpitRemoteBase", LAUNCHER)

    def test_gateway_serves_raw_branch_index_as_html(self):
        self.assertIn("$remotePath=if($path -eq '/'){'/index.html'}else{$path}", GATEWAY)
        self.assertIn("$ct=Get-ContentType $remotePath", GATEWAY)
        self.assertIn("if($ct -eq 'application/octet-stream'", GATEWAY)


if __name__ == "__main__":
    unittest.main()
