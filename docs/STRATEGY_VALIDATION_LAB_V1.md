# Strategy Validation Lab v1

This layer evaluates research results after backtest/replay rather than trusting headline win rate.

Each run carries train and out-of-sample expectancy, trade count, gross expectancy, explicit per-trade cost, MAE/MFE, market regime and symbol class. The validator rejects insufficient samples, non-positive out-of-sample expectancy, edges erased by costs, invalid excursion metrics and severe train-to-test decay.

Results are partitioned by strategy × regime × symbol class so a method can be useful in one context and rejected in another. The initial numeric thresholds are conservative scaffolding and must later be calibrated from evidence.

Future folds should use chronological walk-forward windows and multiple-testing controls. PASS means eligible for the next research gate only; it never authorizes real orders.
