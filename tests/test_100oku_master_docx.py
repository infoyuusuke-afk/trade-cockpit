import unittest
from pathlib import Path

from scripts.build_100oku_master_docx import DOCX, MARKDOWN, blocks, read_docx_blocks

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "PROJECT PURPOSE / 100億円最上位目的",
    "Single Source of Truth",
    "Current Architecture",
    "Current Acceptance / PASS / PARTIAL / BLOCKED / NOT_RUN",
    "Market Universe / Dynamic Screening",
    "Candidate Generators",
    "Correlation / Lead-Lag Research Engine",
    "AI BRAIN PICKS",
    "BASELINE / Research Layer / Meta Brain / AI SHADOW",
    "Research Data Registry",
    "Data freshness / available_at / no-lookahead",
    "TradingView / MS2-RSS / DEX等データ役割",
    "Entertainment / AIトレード日記",
    "Distribution / Monetization / Revenue Engine",
    "Continuous Evolution",
    "Anti-Stagnation",
    "OMISSION AUDIT",
    "Owner / ChatGPT / Cursor / Codex役割",
    "日次16:30 MASTER棚卸し",
    "Change Management",
    "HANDOVER / 別AI復旧手順",
    "Safety / real_submit_allowed=false",
)


def _same(left, right) -> bool:
    if left[0] == "code":
        return right[0] == "paragraph" and right[1] == left[1]
    return left == right


class MasterDocxTests(unittest.TestCase):
    def test_word_matches_markdown_and_keeps_the_safety_line(self):
        markdown = MARKDOWN.read_text(encoding="utf-8")
        self.assertGreater(MARKDOWN.stat().st_size, 20000)
        headings = [block[2] for block in blocks(markdown) if block[0] == "heading" and block[1] == 2]
        self.assertEqual(list(REQUIRED), headings)
        doc_blocks = read_docx_blocks(DOCX)
        md_blocks = blocks(markdown)
        self.assertEqual(len(md_blocks), len(doc_blocks))
        for left, right in zip(md_blocks, doc_blocks):
            self.assertTrue(_same(left, right), (left, right))
        self.assertIn("real_submit_allowed=false", markdown)
        self.assertIn("SNAPSHOT", markdown)
        self.assertIn("BASELINE_N=0", markdown)
        self.assertNotIn("G0 から G5 のライブ PASS", markdown.split("OMISSION AUDIT")[0])
        self.assertIn("MASTER_SPEC_SYNC=PASS", markdown)
