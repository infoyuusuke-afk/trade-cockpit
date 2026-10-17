"""Prevent public snapshots and stale Collector data from being shown as LIVE."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract_live_script():
    source = (ROOT / "scripts" / "update.py").read_text(encoding="utf-8")
    marker = '    ms2_live_script = r"""'
    start = source.index(marker) + len(marker)
    return source[start:source.index('\n"""', start)]


class LocalOnlyMs2GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = extract_live_script()
        cls.page = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_generated_page_exactly_matches_script(self):
        # V10's local Gateway index uses its own fetch path. Preserve
        # identical safety semantics rather than silently declaring the
        # generated legacy inline script to be the new V10 implementation.
        if (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").is_file():
            # V10 transport marks public/cached/failed local responses
            # unusable, and the full price provenance check remains.
            self.assertIn('d._transport_fail_closed=true', self.page)
            self.assertIn('d.stale=true', self.page)
            self.assertIn('d.real_submit_allowed=false', self.page)
            self.assertIn('window.livePriceBlocked', self.page)
            self.assertIn('CACHED_OR_SAMPLE_PAYLOAD', self.page)
            self.assertIn('staleFromAge=d.stale||age>60||age< -5', self.page)
            # The dashboard must not render any stale top/held/PTS/IR
            # prices, and transport errors must erase prior cards.
            for field, alias in (
                ("top5", "xs"), ("hold_top5", "holds"),
                ("pts_top5", "pts"), ("ir_pts_top5", "ir")
            ):
                self.assertIn(
                    f'const {alias}=!stale&&Array.isArray(d.{field})?d.{field}:[];',
                    self.page
                )
            self.assertIn('if(cards)cards.innerHTML=""', self.page)
            self.assertIn('if(holdCards)holdCards.innerHTML=""', self.page)
            self.assertIn('if(ptsCards)ptsCards.innerHTML=""', self.page)
            self.assertIn('if(irCards)irCards.innerHTML=""', self.page)
            self.assertEqual(
                self.page.count(
                    "const all=d.stale===false&&"
                    "Array.isArray(d.all_targets)?d.all_targets:[]"
                ),
                2
            )
        else:
            self.assertIn(self.script, self.page)

    def test_only_local_collector_can_be_live(self):
        self.assertIn('localSource=d.connection_source==="自宅PC・MS2 RSS LIVE"', self.script)
        self.assertIn("stale=!localSource||!schemaOk||!coverageOk||", self.script)
        self.assertIn('d.connection_source="公開スナップショット"', self.script)

    def test_schema_coverage_and_timestamps_fail_closed(self):
        self.assertIn('schemaOk=d.schema_version==="ms2-common-1.0"', self.script)
        self.assertIn('Number(d.valid)>=Math.max(90,Math.ceil(Number(d.universe)*0.9))', self.script)
        self.assertIn('d.stale!==false||age>60||age< -5', self.script)
        self.assertIn("Infinity", self.script)

    def test_stale_candidates_not_rendered(self):
        for field in ("top5", "hold_top5", "pts_top5", "ir_pts_top5"):
            self.assertIn(f"const {'xs' if field=='top5' else 'holds' if field=='hold_top5' else 'pts' if field=='pts_top5' else 'ir'}=!stale&&Array.isArray(d.{field})?d.{field}:[];", self.script)

    def test_stale_watchlists_not_rendered(self):
        self.assertEqual(
            self.script.count("const all=d.stale===false&&Array.isArray(d.all_targets)?d.all_targets:[]"),
            2,
        )

    def test_failed_fetch_clears_candidate_cards(self):
        self.assertIn('health.textContent="ローカル収集待ち・売買禁止"', self.script)
        self.assertIn('if(cards)cards.innerHTML=', self.script)
        self.assertIn('if(holdCards)holdCards.innerHTML=""', self.script)
        self.assertIn('if(ptsCards)ptsCards.innerHTML=""', self.script)
        self.assertIn('if(irCards)irCards.innerHTML=""', self.script)


if __name__ == "__main__":
    unittest.main()
