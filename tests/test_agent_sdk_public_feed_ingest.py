"""Offline official RSS ingestion regression suite: zero network/model calls."""
import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "agent_sdk_public_feed_ingest.py"
spec = importlib.util.spec_from_file_location("public_feed_ingest", MODULE)
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)

NOW = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)
PUB = "2026-10-20T15:00:00+09:00"
LINK = "https://www.boj.or.jp/whatsnew/2026/20261020_1.htm"


def rss(*, date=PUB, url=LINK, title="Monetary Policy Public Headline"):
    return (f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>{title}</title><link>{url}</link>
<pubDate>{date}</pubDate></item></channel></rss>""").encode("utf-8")


def rdf():
    return (f"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
 <item><title>BOJ statistics test</title>
 <link>{LINK}</link><dc:date>{PUB}</dc:date></item>
 </rdf:RDF>""").encode("utf-8")


class PublicFeedTests(unittest.TestCase):
    def test_jp_macro_and_supply_feeds_produce_valid_existing_sdk_contract(self):
        from datetime import datetime
        import importlib.util
        a = importlib.util.spec_from_file_location(
            "agent_sdk_coordination_pilot", ROOT / "scripts" / "agent_sdk_coordination_pilot.py"
        )
        pilot = importlib.util.module_from_spec(a)
        a.loader.exec_module(pilot)
        snapshot = feed.build_snapshot(
            {"pre_next": rss(), "supply_sq": rdf()}, "feed_synthetic_20261021", NOW
        )
        self.assertEqual(len(snapshot["sources"]), 2)
        self.assertEqual({x["role"] for x in snapshot["sources"]}, {"pre_next", "supply_sq"})
        self.assertTrue(all(x["available_at"] == NOW.isoformat() for x in snapshot["sources"]))
        self.assertEqual(pilot.validate_snapshot(snapshot, NOW), snapshot)

    def test_calendar_day_only_is_observed_at_fetch_not_fake_release_time(self):
        records = feed.parse_feed(rss(date="2026-10-20"), "pre_next", NOW)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["as_of"], NOW.isoformat())
        self.assertEqual(records[0]["available_at"], NOW.isoformat())
        self.assertIn("DATE_ONLY_OBSERVED_AT_FETCH", records[0]["summary"])
        self.assertIn("earliest release TIME UNKNOWN", records[0]["summary"])
        self.assertEqual(records[0]["data_status"], "DATE_ONLY_OBSERVED_AT_FETCH")
        self.assertEqual(records[0]["fetched_at"], NOW.isoformat())
        self.assertEqual(records[0]["source_type"], "OFFICIAL_RSS_HEADLINE")

    def test_missing_or_timezone_naive_clock_stays_blocked(self):
        for stamp in ("", "2026-10-20T15:00:00"):
            with self.subTest(stamp=stamp):
                self.assertEqual(feed.parse_feed(rss(date=stamp), "pre_next", NOW), [])

    def test_date_only_future_and_old_are_rejected(self):
        for stamp in ("2026-10-22", "2026-10-10", "2026-02-30"):
            with self.subTest(stamp=stamp):
                self.assertEqual(feed.parse_feed(rss(date=stamp), "pre_next", NOW), [])

    def test_future_and_stale_fail_closed(self):
        self.assertEqual(feed.parse_feed(rss(date="2026-10-22T02:00:00+09:00"), "supply_sq", NOW), [])
        self.assertEqual(feed.parse_feed(rss(date="2026-10-01T02:00:00+09:00"), "supply_sq", NOW), [])
        with self.assertRaisesRegex(feed.EvidenceBlocked, "NO_DATED_RECENT"):
            feed.build_snapshot({"supply_sq": rss(date="2026-10-01T02:00:00+09:00")},
                                "feed_synthetic_20261021", NOW)

    def test_official_boj_legacy_http_link_normalizes_to_https(self):
        old_link = "http://www.boj.or.jp/whatsnew/2026/20261020_1.htm"
        got = feed.parse_feed(
            rss(date="Tue, 20 Oct 2026 17:00:00 +0900", url=old_link),
            "pre_next", NOW
        )
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["source_url"], LINK)
        self.assertEqual(got[0]["as_of"], "2026-10-20T08:00:00+00:00")
        self.assertEqual(got[0]["available_at"], NOW.isoformat())
        self.assertEqual(got[0]["data_status"], "PUBLICATION_TIME_VERIFIED")

    def test_reject_external_private_and_signed_urls(self):
        for url in ("https://example.org/news", "http://example.org/news",
                    "https://www.boj.or.jp.evil.example/news",
                    "https://www.boj.or.jp/whatsnew?q=token",
                    "https://user:secret@www.boj.or.jp/private",
                    "https://www.boj.or.jp/x#private",
                    "http://www.boj.or.jp:8080/article",
                    "http://www.boj.or.jp:80/article",
                    "https://www.boj.or.jp:443/article",
                    "ftp://www.boj.or.jp/news",
                    "https://www.boj.or.jp/has space"):
            with self.subTest(url=url):
                self.assertEqual(feed.parse_feed(rss(url=url), "pre_next", NOW), [])

    def test_http_and_https_versions_are_one_canonical_evidence_id(self):
        old_link = "http://www.boj.or.jp/whatsnew/2026/20261020_1.htm"
        one = feed.parse_feed(rss(url=old_link), "pre_next", NOW)
        two = feed.parse_feed(rss(url=LINK), "pre_next", NOW)
        self.assertEqual(len(one), 1)
        self.assertEqual(one[0]["source_id"], two[0]["source_id"])
        self.assertEqual(one[0]["source_url"], two[0]["source_url"])

    def test_no_dtd_entity_processing(self):
        injected = b'<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss/>'
        with self.assertRaisesRegex(feed.EvidenceBlocked, "DTD_FORBIDDEN"):
            feed.parse_feed(injected, "pre_next", NOW)

    def test_no_overwrite_and_no_network_mode_by_default(self):
        snapshot = feed.build_snapshot({"supply_sq": rss()}, "feed_synthetic_20261021", NOW)
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "public_feed.json"
            feed.write_once(target, snapshot)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), snapshot)
            with self.assertRaisesRegex(feed.EvidenceBlocked, "OUTPUT_ALREADY_EXISTS"):
                feed.write_once(target, snapshot)

    def test_fetch_only_allowlisted_official_feeds(self):
        with self.assertRaisesRegex(feed.EvidenceBlocked, "ENDPOINT_NOT_ALLOWLISTED"):
            feed.fetch_official_feed("https://example.org/rss")

    def test_no_duplicate_source_even_for_repeated_item(self):
        raw = rss()
        item = raw.split(b"<item>")[1].split(b"</item>")[0]
        raw = raw.replace(b"</channel>", b"<item>" + item + b"</item></channel>")
        self.assertEqual(len(feed.parse_feed(raw, "pre_next", NOW)), 1)


if __name__ == "__main__":
    unittest.main()
