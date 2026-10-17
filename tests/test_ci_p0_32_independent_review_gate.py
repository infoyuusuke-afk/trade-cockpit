"""P0-32 independent-review gate must reject self, bots, stale and ambiguous proof."""
import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("reviewgate",ROOT/"scripts/ci_p0_32_independent_review_gate.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
HEAD="a"*40

def pr(draft=False):
    return {"user":{"login":"original-owner"},"head":{"sha":HEAD},"draft":draft,"merged":False}

def review(login="independent-reviewer",state="APPROVED",commit=HEAD,when="2026-10-17T10:00:00Z",rid=1,kind="User"):
    return {"user":{"login":login,"type":kind},"state":state,"commit_id":commit,
            "submitted_at":when,"id":rid}

class ReviewAdmission(unittest.TestCase):
    def test_independent_current_head_only(self):
        self.assertEqual(module.verdict(pr(),[review()]),"APPROVED_INDEPENDENT_CURRENT_HEAD")
    def test_no_review_is_blocked(self):
        self.assertTrue(module.verdict(pr(),[]).startswith("BLOCKED"))
    def test_draft_is_blocked_even_with_approval(self):
        self.assertEqual(module.verdict(pr(True),[review()]),"BLOCKED_DRAFT_OR_MERGED")
    def test_author_approval_is_never_independent(self):
        self.assertTrue(module.verdict(pr(),[review(login="original-owner")]).startswith("BLOCKED"))
    def test_bot_approval_is_never_independent(self):
        self.assertTrue(module.verdict(pr(),[review(login="copilot[bot]",kind="Bot")]).startswith("BLOCKED"))
    def test_previous_head_approval_is_stale(self):
        self.assertTrue(module.verdict(pr(),[review(commit="b"*40)]).startswith("BLOCKED"))
    def test_later_rejection_overrides_approval(self):
        rs=[review(),review(state="CHANGES_REQUESTED",when="2026-10-17T11:00:00Z",rid=2)]
        self.assertTrue(module.verdict(pr(),rs).startswith("BLOCKED"))
    def test_new_approval_can_replace_rejection(self):
        rs=[review(state="CHANGES_REQUESTED",rid=1),review(when="2026-10-17T11:00:00Z",rid=2)]
        self.assertEqual(module.verdict(pr(),rs),"APPROVED_INDEPENDENT_CURRENT_HEAD")
    def test_comment_is_not_approval(self):
        self.assertTrue(module.verdict(pr(),[review(state="COMMENTED")]).startswith("BLOCKED"))
    def test_unknown_head_rejected(self):
        x=pr();x["head"]["sha"]="INVALID"
        self.assertEqual(module.verdict(x,[review()]),"BLOCKED_HEAD")
    def test_missing_fields_fail_closed(self):
        self.assertEqual(module.verdict({},[]),"BLOCKED_UNVERIFIED")

if __name__=="__main__": unittest.main()
