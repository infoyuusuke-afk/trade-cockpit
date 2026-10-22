"""Synthetic negative/state-transition tests: no network, broker or live V10."""
import copy
from datetime import datetime, timezone, timedelta
import unittest
from scripts.gnh01_intelligence_contract_v1 import (
    ContractBlocked, LANE, SCHEMA_VERSION, content_digest, validate_event,
)

NOW = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)


def fixture():
    x = dict(schema_version=SCHEMA_VERSION, event_id="SYN-GNH01-001",
             source_role="grok_bot_gnh01", original_source_url="https://example.com/ir/123",
             original_issuer="Synthetic issuer", event_type="IR", affected_region="JP",
             published_at="2026-10-21T23:00:00Z", provider_available_at="2026-10-21T23:01:00Z",
             grok_first_seen_at="2026-10-21T23:05:00Z",
             grok_reported_at="2026-10-21T23:06:00Z",
             bridge_received_at="2026-10-21T23:07:00Z",
             event_title="Synthetic event", event_summary="Synthetic only, not an investment signal",
             related_japanese_stocks=[{"security_code": "285A", "official_company_name": "キオクシアホールディングス株式会社"}],
             evidence_status="UNVERIFIED", novelty_status="TRUE_NEW", event_revision=1,
             data_lane=LANE, real_submit_allowed=False, content_hash="")
    x["content_hash"] = content_digest(x)
    return x


class ContractTests(unittest.TestCase):
    def reject(self, update, reason):
        x = fixture()
        update(x)
        with self.assertRaisesRegex(ContractBlocked, reason):
            validate_event(x, now=NOW)

    def test_valid_is_archive_only_not_brain_or_shadow(self):
        v = validate_event(fixture(), now=NOW)
        self.assertEqual(v["state"], "ARCHIVE_RESEARCH_ONLY")
        self.assertIsNone(v["available_at"])
        self.assertFalse(v["available_at_verified"])
        self.assertEqual(v["claimed_bridge_received_at"], "2026-10-21T23:07:00+00:00")
        self.assertIs(v["real_submit_allowed"], False)
        self.assertIs(v["shadow_eligible"], False)
        self.assertIs(v["brain_receiver_ack_verified"], False)

    def test_untrusted_receive_time_cannot_backdate_available_at(self):
        x = fixture()
        y = copy.deepcopy(x)
        y["bridge_received_at"] = "2026-10-21T23:06:00Z"
        # The content digest deliberately excludes delivery metadata; a
        # sender can change the claimed receipt without changing the hash.
        self.assertEqual(x["content_hash"], y["content_hash"])
        a = validate_event(x, now=NOW)
        b = validate_event(y, now=NOW)
        self.assertIsNone(a["available_at"])
        self.assertIsNone(b["available_at"])
        self.assertFalse(b["available_at_verified"])
        self.assertNotEqual(a["claimed_bridge_received_at"],
                            b["claimed_bridge_received_at"])
        self.assertFalse(b["shadow_eligible"])

    def test_sender_primary_claim_never_proves_authenticity(self):
        x = fixture()
        x["evidence_status"] = "PRIMARY_VERIFIED"
        x["content_hash"] = content_digest(x)
        self.assertFalse(validate_event(x, now=NOW)["source_authenticity_verified"])

    def test_true_order_flag_blocked_even_if_resigned(self):
        self.reject(lambda x: x.update(real_submit_allowed=True), "SCHEMA_OR_SAFETY")

    def test_unexpected_field_blocked(self):
        self.reject(lambda x: x.update(order_api="broker"), "EVENT_FIELDS_INVALID")

    def test_tampered_content_hash_blocked(self):
        self.reject(lambda x: x.update(event_summary="tampered"), "CONTENT_HASH_MISMATCH")

    def test_non_utc_clock_blocked_even_if_resigned(self):
        def f(x):
            x["published_at"] = "2026-10-22T08:00:00+09:00"
            x["content_hash"] = content_digest(x)
        self.reject(f, "UTC_TIMESTAMP_REQUIRED")

    def test_future_time_blocked(self):
        def f(x):
            x["grok_reported_at"] = "2026-10-23T01:00:00Z"
            x["content_hash"] = content_digest(x)
        self.reject(f, "FUTURE_EVENT_TIMESTAMP")

    def test_publication_after_detection_blocked(self):
        def f(x):
            x["published_at"] = "2026-10-21T23:06:30Z"
            x["content_hash"] = content_digest(x)
        self.reject(f, "PUBLICATION_SEQUENCE_INVALID")

    def test_grok_seen_after_report_blocked(self):
        def f(x):
            x["grok_first_seen_at"] = "2026-10-21T23:06:30Z"
            x["content_hash"] = content_digest(x)
        self.reject(f, "GROK_SEQUENCE_INVALID")

    def test_duplicate_ticker_blocked(self):
        def f(x):
            x["related_japanese_stocks"].append(copy.deepcopy(x["related_japanese_stocks"][0]))
            x["content_hash"] = content_digest(x)
        self.reject(f, "STOCK_IDENTITY_INVALID")

    def test_localhost_source_blocked(self):
        def f(x):
            x["original_source_url"] = "https://localhost.local/secret"
            x["content_hash"] = content_digest(x)
        self.reject(f, "PUBLIC_HTTPS_SOURCE_REQUIRED")

    def test_query_secret_url_blocked(self):
        def f(x):
            x["original_source_url"] = "https://example.com/ir?token=private"
            x["content_hash"] = content_digest(x)
        self.reject(f, "PUBLIC_HTTPS_SOURCE_REQUIRED")

    def test_unknown_published_at_preserves_unknown(self):
        x = fixture()
        x["published_at"] = None
        x["content_hash"] = content_digest(x)
        self.assertEqual(validate_event(x, now=NOW)["state"], "ARCHIVE_RESEARCH_ONLY")

    def test_relay_time_does_not_change_event_identity(self):
        x = fixture()
        y = copy.deepcopy(x)
        y["bridge_received_at"] = "2026-10-21T23:08:00Z"
        y["grok_reported_at"] = "2026-10-21T23:07:00Z"
        self.assertEqual(content_digest(x), content_digest(y))
        self.assertEqual(validate_event(y, now=NOW)["content_hash"], x["content_hash"])

    def test_revision_changes_hash(self):
        x = fixture()
        y = copy.deepcopy(x)
        y["event_revision"] = 2
        self.assertNotEqual(content_digest(x), content_digest(y))

    def test_boolean_revision_blocked(self):
        def f(x):
            x["event_revision"] = True
            x["content_hash"] = content_digest(x)
        self.reject(f, "EVENT_ID_OR_REVISION_INVALID")


class StructuralSchemaTests(unittest.TestCase):
    def test_schema_matches_semantic_validator_field_set(self):
        import json
        from pathlib import Path
        from scripts.gnh01_intelligence_contract_v1 import REQUIRED
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" /
                             "intelligence_event_v1.schema.json").read_text("utf-8"))
        self.assertEqual(set(schema["required"]), REQUIRED)
        self.assertEqual(set(schema["properties"]), REQUIRED)
        self.assertIs(schema["additionalProperties"], False)

    def test_schema_validates_fixture_if_jsonschema_available(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("optional jsonschema dependency unavailable")
        import json
        from pathlib import Path
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" /
                             "intelligence_event_v1.schema.json").read_text("utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(fixture())), [])


if __name__ == "__main__":
    unittest.main()
