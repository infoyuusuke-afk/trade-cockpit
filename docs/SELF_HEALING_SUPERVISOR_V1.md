# Self-Healing Supervisor v1

The target is **zero routine Owner intervention**, not the impossible promise that external failures never occur.

Known failures map to deterministic recovery playbooks. Unknown failures quarantine themselves and enter SAFE. Data uncertainty ends in WAIT_DATA; strategy regression falls back toward Shadow; execution anomalies freeze new orders before reconciliation; publication failures hold the draft; AI disagreement resolves toward stronger evidence and the safer state.

Every incident is recorded for later engineering review, but routine recovery does not ask the Owner to operate the system.

This v1 is a pure recovery planner. It has no broker, scheduler, credential, restart or publication side effect.
