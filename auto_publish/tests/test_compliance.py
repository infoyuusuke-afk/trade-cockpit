import copy
import json
import unittest

from auto_publish.app.compliance.rules import check_captions_srt, check_post, enforce
from auto_publish.app.errors import ComplianceError
from auto_publish.app.pipeline import _draft, build_drafts
from auto_publish.tests.helpers import SESSION, FakeRenderer, PipelineCase

SHA = "a" * 64


def _post(lang="en-US", **kw):
    p = {
        "lang": lang, "session_date": SESSION, "title": "Tokyo close: X +1.0%", "fixture": False,
        "caption": "caption", "hashtags": [],
        "source_refs": [
            {"fact_id": "f_m", "kind": "mover", "basis": "observed", "session_date": SESSION, "sha256": SHA},
            {"fact_id": "f_p", "kind": "paper_trade", "basis": "paper", "session_date": SESSION, "sha256": SHA},
        ],
        "segments": [
            {"id": "hook", "type": "hook", "fact_ids": ["f_m"], "text": "X rose 1.0% in Tokyo."},
            {"id": "b1", "type": "close", "fact_ids": ["f_m"], "text": "It closed at ¥100."},
            {"id": "b2", "type": "paper", "fact_ids": ["f_p"], "text": "Paper trade (simulated): long, +1.0R."},
            {"id": "disclaimer", "type": "disclaimer", "fact_ids": [],
             "text": "Not investment advice. Paper results are simulated."},
        ],
    }
    p.update(kw)
    return p


def _rules(post):
    return {v["rule"] for v in check_post(post, SESSION)}


def _set_text(post, seg_id, text):
    p = copy.deepcopy(post)
    next(s for s in p["segments"] if s["id"] == seg_id)["text"] = text
    return p


class TestRules(unittest.TestCase):
    def test_clean_post_passes(self):
        self.assertEqual(check_post(_post(), SESSION), [])

    def test_banned_phrases_en(self):
        for bad in ("This is guaranteed to rise.", "Risk-free setup.", "Easy money today.", "You must buy this.",
                    "Buy now before it runs.", "100% win rate.", "You cannot lose."):
            self.assertIn("BANNED_PHRASE", _rules(_set_text(_post(), "b1", bad)), bad)

    def test_banned_phrases_ja(self):
        base = _post("ja-JP")
        base["segments"][2]["text"] = "ペーパートレード：買い。"
        base["segments"][3]["text"] = "投資助言ではありません。結果はシミュレーションです。"
        for bad in ("必ず儲かる銘柄。", "絶対に上がる。", "元本保証です。", "今すぐ買いましょう。", "爆益確定。"):
            self.assertIn("BANNED_PHRASE", _rules(_set_text(base, "b1", bad)), bad)

    def test_unsupported_profit_claim(self):
        post = _set_text(_post(), "b1", "We made ¥50,000 profit on this move.")
        self.assertIn("UNSUPPORTED_PROFIT_CLAIM", _rules(post))
        ja = _post("ja-JP")
        ja["segments"][2]["text"] = "ペーパートレード：買い。"
        ja["segments"][3]["text"] = "投資助言ではありません。結果はシミュレーションです。"
        self.assertIn("UNSUPPORTED_PROFIT_CLAIM", _rules(_set_text(ja, "b1", "今日は5万円の利益。")))

    def test_profit_wording_allowed_when_backed_by_labelled_trade_fact(self):
        post = _set_text(_post(), "b2", "Paper trade (simulated): the return was +1.0R.")
        self.assertEqual(_rules(post), set())

    def test_paper_result_must_be_labelled(self):
        post = _set_text(_post(), "b2", "Long from ¥100, closed at +1.0R.")
        self.assertIn("PAPER_NOT_LABELED", _rules(post))
        post = _set_text(_post(), "disclaimer", "Not investment advice.")
        self.assertIn("PAPER_NOT_LABELED", _rules(post))

    def test_real_account_results_rejected(self):
        post = _post()
        post["source_refs"][1]["basis"] = "real"
        self.assertIn("REAL_ACCOUNT_RESULT", _rules(post))

    def test_missing_source_refs(self):
        post = _post()
        post["segments"][1]["fact_ids"] = []
        self.assertIn("MISSING_SOURCE_REFS", _rules(post))
        post = _post()
        post["segments"][1]["fact_ids"] = ["f_unknown"]
        self.assertIn("MISSING_SOURCE_REFS", _rules(post))

    def test_date_mismatch(self):
        self.assertIn("DATE_MISMATCH", _rules(_post(session_date="2026-09-23")))
        post = _post()
        post["source_refs"][0]["session_date"] = "2026-09-23"
        self.assertIn("DATE_MISMATCH", _rules(post))

    def test_empty_script_and_caption(self):
        self.assertIn("EMPTY_TEXT", _rules(_set_text(_post(), "b1", "   ")))
        self.assertIn("EMPTY_TEXT", _rules(_post(caption="")))
        self.assertIn("EMPTY_TEXT", _rules(_post(segments=[])))
        self.assertIn("EMPTY_TEXT", _rules(_post(title="")))

    def test_empty_captions_srt(self):
        self.assertTrue(check_captions_srt(""))
        self.assertTrue(check_captions_srt("1\n00:00:00,000 --> 00:00:06,000\n"))
        self.assertFalse(check_captions_srt("1\n00:00:00,000 --> 00:00:06,000\nHello\n"))

    def test_disclaimer_required(self):
        post = _post()
        post["segments"] = [s for s in post["segments"] if s["type"] != "disclaimer"]
        self.assertIn("DISCLAIMER_MISSING", _rules(post))

    def test_fixture_must_be_labelled(self):
        self.assertIn("FIXTURE_NOT_LABELED", _rules(_post(fixture=True)))

    def test_enforce_raises_with_all_violations(self):
        with self.assertRaises(ComplianceError) as cm:
            enforce([_set_text(_post(), "b1", "Guaranteed profit!"), _post(session_date="2026-01-01")], SESSION)
        rules = {v["rule"] for v in cm.exception.violations}
        self.assertTrue({"BANNED_PHRASE", "UNSUPPORTED_PROFIT_CLAIM", "DATE_MISMATCH"} <= rules)


class TestCompliancePipeline(PipelineCase):
    def test_generated_drafts_pass_and_label_paper(self):
        self.ingest_validate()
        results = build_drafts(self.ctx, SESSION, FakeRenderer())
        t1 = next(r["story_id"] for r in results
                  if self.ctx.conn.execute("SELECT topic FROM stories WHERE story_id=?", (r["story_id"],)).fetchone()[0]
                  == "TEST1.T")
        en = _draft(self.ctx, t1, "en-US")
        ja = _draft(self.ctx, t1, "ja-JP")
        self.assertEqual(check_post(en, SESSION), [])
        self.assertEqual(check_post(ja, SESSION), [])
        paper_en = next(s for s in en["segments"] if s["type"] == "paper")["text"]
        self.assertIn("Paper trade (simulated, not real money)", paper_en)
        self.assertIn("ペーパートレード", next(s for s in ja["segments"] if s["type"] == "paper")["text"])
        self.assertIn("TEST FIXTURE", en["segments"][-1]["text"])

    def test_compliance_failure_is_fail_closed_and_not_retryable(self):
        self.ingest_validate()
        import auto_publish.app.pipeline as pl
        original = pl.localize

        def bad_localize(script, lang):
            post = original(script, lang)
            post["segments"][1]["text"] += " Guaranteed."
            return post

        pl.localize = bad_localize
        try:
            results = build_drafts(self.ctx, SESSION, FakeRenderer())
        finally:
            pl.localize = original
        for r in results:
            self.assertEqual(r["state"], "FAILED")
            self.assertEqual(r["error"]["code"], "COMPLIANCE_REJECTED")
            self.assertIsNone(self.ctx.conn.execute(
                "SELECT 1 FROM artifacts WHERE story_id = ?", (r["story_id"],)).fetchone(), "nothing rendered")
            with self.assertRaises(Exception) as cm:
                pl.retry(self.ctx, r["story_id"], "try again", FakeRenderer())
            self.assertEqual(getattr(cm.exception, "code", None), "NOT_RETRYABLE")
        err = json.loads(self.ctx.conn.execute("SELECT last_error FROM stories").fetchone()[0])
        self.assertEqual(err["details"]["violations"][0]["rule"], "BANNED_PHRASE")


if __name__ == "__main__":
    unittest.main()
