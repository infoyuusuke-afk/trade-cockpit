"""Error taxonomy for the Auto Publish pipeline.

Every stage failure is classified into one of two families:

* ``FailClosedError`` -- the pipeline must stop and the story/session is moved
  to ``FAILED``. Nothing downstream (render, schedule, publish) may run.
* ``TransientError`` -- the operation may be retried (bounded by
  ``max_attempts``). While attempts remain the story stays in its current
  state; once attempts are exhausted it is moved to ``FAILED`` (fail-closed).

Unexpected exceptions are always treated as fail-closed.
"""
from __future__ import annotations


class AutoPublishError(Exception):
    """Base class. ``code`` is a stable machine-readable identifier."""

    code = "AUTO_PUBLISH_ERROR"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        if code:
            self.code = code
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "type": type(self).__name__,
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "details": self.details,
        }


class FailClosedError(AutoPublishError):
    code = "FAIL_CLOSED"


class ValidationError(FailClosedError):
    code = "VALIDATION_FAILED"


class EvidenceError(FailClosedError):
    code = "EVIDENCE_INVALID"


class FactCheckError(FailClosedError):
    code = "FACT_CHECK_FAILED"


class ComplianceError(FailClosedError):
    code = "COMPLIANCE_REJECTED"

    def __init__(self, message: str, violations: list[dict], **kw):
        super().__init__(message, details={"violations": violations}, **kw)
        self.violations = violations


class RenderError(FailClosedError):
    code = "RENDER_FAILED"


class SchedulingError(FailClosedError):
    code = "SCHEDULING_REFUSED"


class ApprovalError(FailClosedError):
    code = "APPROVAL_REFUSED"


class ControlBlockedError(FailClosedError):
    """Raised when PAUSE ALL / DISABLE PLATFORM blocks an action."""

    code = "CONTROL_BLOCKED"


class PublishBlockedError(FailClosedError):
    """Raised by any attempt to reach the PUBLISH stage in release gate R1."""

    code = "PUBLISH_BLOCKED_R1"


class AdapterNotAllowedError(FailClosedError):
    code = "ADAPTER_NOT_ALLOWED"


class StateConflictError(AutoPublishError):
    """Compare-and-set transition lost (state changed underneath us)."""

    code = "STATE_CONFLICT"


class InvalidTransitionError(AutoPublishError):
    code = "INVALID_TRANSITION"


class TransientError(AutoPublishError):
    code = "TRANSIENT"
    retryable = True
