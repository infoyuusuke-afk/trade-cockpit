"""V10 UI lane rationalization and OWNER-pinned FOCUS safeguards.

Synthetic-only. No external market data, Excel, broker, network or orders.
"""
import json
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "index.html"
EARNINGS = ROOT / "earnings-calendar.js"


class V10MissionNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HTML.read_text(encoding="utf-8")
        cls.earnings = EARNINGS.read_text(encoding="utf-8")
        cls.nav = cls.source.split('<nav class="cockpit-tabs"', 1)[1].split("</nav>", 1)[0]

    def test_priority_primary_tabs_preserve_strategies_and_owner(self):
        buttons = re.findall(r'<button class="cockpit-tab(?: active)?" data-tab="([^"]+)"', self.nav)
        self.assertEqual(buttons[:13], [
            "control", "brain", "ai-journal", "scalp", "event-hot",
            "ms2-live", "pre-next", "overnight", "swing", "value",
            "focus-owner", "kioxia-calendar", "events",
        ])
        self.assertEqual(len(buttons), 22)
        self.assertIn('data-tab="earnings"', self.earnings)  # Script-injected tab, not statically duplicated.

    def test_reference_preserves_research_without_empty_weekly(self):
        nav = self.nav
        self.assertIn('data-tab="correlation"', nav)
        self.assertIn('data-tab="wick"', nav)
        self.assertIn('data-tab="expansion"', nav)
        self.assertIn('data-tab="accumulation"', nav)
        self.assertIn('data-tab="policy"', nav)
        self.assertNotIn('data-tab="weekly"', nav)
        self.assertIn('else if(s.id==="weekly-review"||t.includes("週間振り返り"))k="ai-journal"', self.source)

    def test_research_does_not_auto_promote_into_realtime(self):
        self.assertIn('if(s.id==="next-theme-radar")k="pre-next"', self.source)
        self.assertNotIn('s.id==="data-quality-gate"||s.id==="next-theme-radar"', self.source)
        self.assertIn('実発注', self.source)
        self.assertIn('role="status"', self.source)

    def test_remove_historical_false_positive_data_quality_panel(self):
        self.assertNotIn('id="data-quality-gate"', self.source)
        self.assertNotIn("56 / 100銘柄", self.source)
        self.assertNotIn('VERIFIED FORECAST TOP 5', self.source)
        self.assertNotIn('id="action-dashboard"', self.source)
        self.assertNotIn('id="focus-cards"', self.source)

    def test_focus_persistent_owner_choices_and_no_automatic_replacement(self):
        s = self.source
        self.assertIn('const key="cockpitFocusPinnedV10"', s)
        self.assertIn('pinned.push(value);save();paint()', s)
        self.assertIn('pinned=pinned.filter(t=>t!==select.value)', s)
        self.assertIn('if(pinned.length>=5)', s)
        self.assertIn('^[0-9A-Z]{4,5}', s)
        self.assertIn('const validMarket=d=>{', s)
        self.assertIn('lastVerified=validMarket(d)', s)
        focus = s.split('<section id="focus-owner-panel"', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("fetch(", focus)
        self.assertNotIn("cockpitAnnounce", focus)
        self.assertNotIn("RssOrder", focus)

    def test_kioxia_updated_in_fixed_scalp_selection(self):
        self.assertIn('const fixed=["464A.T","9984.T","8035.T","6920.T","6857.T"]', self.source)
        self.assertNotIn('const fixed=["285A.T"', self.source)

    def test_existing_visual_colors_and_modules_kept(self):
        s = self.source
        for marker in (
            "background:#131722f2", "background:#2962ff",
            "color:#089981", "background:#050506",
            'src="trade_control.js?v=', 'src="v10_publication_status.js?v=',
        ):
            self.assertIn(marker, s)

    def test_only_verified_ms2_identity_and_freshness_can_paint_focus(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable: static source contract tests still run")
        raw = self.source.split("const validMarket=d=>{", 1)[1].split("\n };", 1)[0]
        func = "const validMarket=d=>{" + raw + "\n };"
        js = func + r"""
const window = {livePriceBlocked: d => d.source==="MarketSpeed II RSS / local PC" ? "" : "BAD_SOURCE"};
const original = {
 stale:false,source_authenticated:true,live_values_available:true,data_conflict:false,
 real_submit_allowed:false,_transport_fail_closed:false,source:"MarketSpeed II RSS / local PC",
 updated_at:new Date(Date.now()-30000).toISOString()
};
const cases=[
  validMarket(original),
  validMarket({...original,stale:true}),
  validMarket({...original,source_authenticated:false}),
  validMarket({...original,live_values_available:false}),
  validMarket({...original,data_conflict:null}),
  validMarket({...original,real_submit_allowed:true}),
  validMarket({...original,_transport_fail_closed:true}),
  validMarket({...original,source:"Historical data"}),
  validMarket({...original,updated_at:new Date(Date.now()-3600000).toISOString()}),
  validMarket({...original,updated_at:new Date(Date.now()+180000).toISOString()}),
  validMarket({...original,updated_at:"2026-10-20 10:00:00"}),
  validMarket({...original,updated_at:null}),
];
process.stdout.write(JSON.stringify(cases));
"""
        run = subprocess.run([node, "-e", js], text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        cases = json.loads(run.stdout)
        self.assertEqual(cases, [True] + [False] * 11)


if __name__ == "__main__":
    unittest.main()
