# AI Cockpit Daily Status v1

The Owner should not need to inspect separate subsystems to understand whether the day is progressing.

The single-entry status reduces internal state to a few operational states: Japan-market daily PREPARING / WAIT_DATA / QUALITY_BLOCKED / READY_FOR_REVIEW, personal trade analysis ACTIVE / NO_PERSONAL_TRADE, and Entertainment CANDIDATE / IDLE.

A no-trade day is normal and does not downgrade a verified Japan-market daily. This status is presentation only; it cannot submit an order or publish externally.
