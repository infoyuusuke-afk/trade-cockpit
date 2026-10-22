"""Read-only compatibility validator for GNH01's observed public DELIVERY_TEST.

This is NOT market intake, transport, role authentication, or deployment.
Only the exact legacy observational field shape is accepted.
"""
from datetime import datetime, timedelta, timezone
import re

FIELDS = frozenset({
    "message_id", "event_type", "source_role", "recipient_role",
    "project_item_id", "state", "real_submit_allowed", "routine_run_id",
    "scheduled_fire_jst", "actual_start_jst", "marker", "note",
})
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
SCHEDULE = re.compile(
    r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) \(slot (\d{2}:\d{2})\)\Z"
)
MARKER = re.compile(r"GNH01-MARK-[a-f0-9]{8,64}\Z")


def validate_observed_test(values: dict[str, str], *, now=None) -> dict[str, str]:
    if set(values) != FIELDS:
        raise ValueError("DELIVERY_TEST_FIELDS_INVALID")
    if (values["event_type"] != "DELIVERY_TEST"
            or values["source_role"] != "global_news_hunter_01"
            or values["recipient_role"] != "development_lead"
            or values["state"] != "ROUTINE_SCHEDULED_TEST"
            or values["real_submit_allowed"] != "false"
            or values["routine_run_id"] != "UNKNOWN"
            or not ID.fullmatch(values["message_id"])
            or not ID.fullmatch(values["project_item_id"])
            or not MARKER.fullmatch(values["marker"])
            or not values["note"].startswith("Synthetic delivery test only.")):
        raise ValueError("DELIVERY_TEST_UNSAFE_OR_UNVERIFIED")
    match = SCHEDULE.fullmatch(values["scheduled_fire_jst"])
    if match is None:
        raise ValueError("DELIVERY_TEST_SCHEDULE_INVALID")
    try:
        scheduled = datetime.strptime(match.group(1) + " " + match.group(2),
                                      "%Y-%m-%d %H:%M")
        datetime.strptime(match.group(3), "%H:%M")
        actual = datetime.strptime(values["actual_start_jst"],
                                   "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("DELIVERY_TEST_CLOCK_INVALID") from exc
    if not scheduled <= actual <= scheduled + timedelta(minutes=30):
        raise ValueError("DELIVERY_TEST_CHRONOLOGY_INVALID")
    at = now or datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise ValueError("NAIVE_CLOCK")
    if actual.replace(tzinfo=timezone(timedelta(hours=9))) > at + timedelta(minutes=5):
        raise ValueError("FUTURE_TIMESTAMP")
    # Never add evidence_url, sent_at_jst or owner_approval_boundary by guessing.
    # This record is observable on GitHub but not a schema-v1 authenticated source.
    return values
