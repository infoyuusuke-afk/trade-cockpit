import unittest

from scripts.live_commentary import commentary_candidate


class CommentarySessionGuardTest(unittest.TestCase):
    def event(self, text, state, quality="VALID"):
        return {
            "event_id": "regression-1500-jst",
            "severity": "NOTICE",
            "timestamp": "2026-09-24T15:00:00+09:00",
            "payload": {
                "commentary_text": text,
                "session_state": state,
                "data_quality": quality,
            },
        }

    def test_not_open_yet_does_not_say_unconfirmed(self):
        self.assertIsNone(commentary_candidate(
            self.event("米国市場は未確認です", "NOT_OPEN_YET")
        ))

    def test_closed_known_does_not_say_missing(self):
        self.assertIsNone(commentary_candidate(
            self.event("US cash missing", "CLOSED_KNOWN")
        ))

    def test_real_invalid_open_feed_warning_is_kept(self):
        row = commentary_candidate(
            self.event("市場データ取得不能", "OPEN", "INVALID")
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["real_submit_allowed"], False)


if __name__ == "__main__":
    unittest.main()
