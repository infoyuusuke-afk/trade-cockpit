"""Issue #282 read-only input bridge: synthetic comments only, no network, no GitHub write."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scripts import coord_issue282_reader as reader

NOW = datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)


def comment(cid, body, at="2026-10-19T10:00:00Z"):
    return {"id": cid, "created_at": at, "html_url": "https://github.com/o/r/issues/282#issuecomment-%d" % cid, "body": body}


def block(**kv):
    return "[100B_COORD_V1]\n" + "\n".join("%s: %s" % (k, v) for k, v in kv.items()) + "\nfree text: ignored"


COMMENTS = [
    comment(1, block(message_id="PRENEXT-01", event_type="REPORT", source_role="pre_next",
                     recipient_role="progress_coordinator", state="WRITE_PROBE")),
    comment(2, block(message_id="ACK-PRENEXT-01", event_type="ACK", source_role="progress_coordinator",
                     recipient_role="pre_next", in_reply_to="PRENEXT-01"), at="2026-10-19T10:02:00Z"),
    comment(3, block(message_id="SD-01", event_type="REPORT", source_role="supply_demand_analyst",
                     recipient_role="progress_coordinator")),
    comment(4, block(message_id="DEV-01", event_type="REPORT", source_role="development_lead",
                     recipient_role="progress_coordinator")),                 # not a specialist
    comment(5, "no marker\nmessage_id: X-01\nevent_type: REPORT\nsource_role: pre_next"),
    comment(6, block(message_id="PRENEXT-01", event_type="REPORT", source_role="pre_next")),   # duplicate id
    comment(7, block(message_id="bad id with spaces", event_type="REPORT", source_role="revenue_hunter")),
]


class Reader(unittest.TestCase):
    def test_ingest_once_and_status(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "c.sqlite"
            got = reader.ingest(COMMENTS, db, fetched_at=NOW)
            self.assertEqual((got["new"], got["duplicate"]), (3, 1))
            st = got["status"]
            self.assertEqual((st["pre_next"]["latest_report"], st["pre_next"]["coordinator_ack"]), ("PRENEXT-01", "ACK-PRENEXT-01"))
            self.assertEqual(st["supply_sq"]["latest_report"], "SD-01")            # alias of supply_sq
            self.assertEqual(st["revenue_hunter"]["report_direction"], "NO_REPORT_SEEN")
            self.assertEqual({v["return_direction"] for v in st.values()}, {"HANDOFF_PENDING"})
            again = reader.ingest(COMMENTS, db, fetched_at=NOW)
            self.assertEqual((again["new"], again["duplicate"]), (0, 4))

    def test_json_lines_and_cli(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "c.jsonl"
            src.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in COMMENTS), encoding="utf-8")
            self.assertEqual(len(reader.load_comments(src)), len(COMMENTS))
            self.assertEqual(reader.main(["--comments-json", str(src), "--db", str(Path(d) / "x.sqlite")]), 0)
            self.assertEqual(reader.main(["--comments-json", str(Path(d) / "missing.json"), "--db", str(Path(d) / "y.sqlite")]), 2)

    def test_values_are_never_invented(self):
        meta = reader.parse_block(block(message_id="M-1", event_type="REPORT", source_role="pre_next"))
        self.assertNotIn("in_reply_to", meta)
        self.assertIsNone(reader.parse_block("[100B_COORD_V1]\nevent_type: REPORT"))   # no message_id


if __name__ == "__main__":
    unittest.main()
