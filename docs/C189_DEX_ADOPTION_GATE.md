# C-189 DEX adoption gate

This research must not change formal signals or order routing.

A DEX feature is eligible for later cockpit consideration only when all are true:

1. Walk-forward evaluation uses prior sessions only.
2. Combined model is compared against the same baseline sample.
3. Open-gap and post-open targets are evaluated separately.
4. Results report N and are split by weekday/weekend-holiday/multi-day-gap regime.
5. Missing DEX observations are excluded, never forward-filled across the decision snapshot.
6. Improvement is not declared from direction hit-rate alone; MAE and stability across folds/regimes are also required.
7. Minimum reliable sample remains N >= 30 per evaluated slice; below that is exploratory.
8. Any future threshold must be learned from training data only and frozen before the test slice.
9. Formal signal/order integration requires a separate PR and explicit approval.

Primary targets:
- open_gap_pct
- open_to_or5_pct
- or5_to_or15_pct
- open_to_0930_pct
- open_to_1000_pct
- open_to_close_pct
