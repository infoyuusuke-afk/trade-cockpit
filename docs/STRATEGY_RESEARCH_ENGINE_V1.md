# Strategy Research Engine v1

The research engine turns the Strategy Registry into a deterministic experiment queue.

It generates single-strategy experiments plus bounded same-horizon pairwise combinations. Cross-horizon combinations are excluded in v1 to keep hypotheses interpretable. Results are admitted to research ranking only when evidence integrity and look-ahead safety pass and the current scaffolding sample floor is met.

Ranking is triage for further research, not a trading recommendation or live permission. Expectancy, drawdown and sample size are retained as measured evidence. Pairwise generation is deliberately bounded to limit combinatorial overfitting.

Future work: regime/symbol-class partitions, walk-forward folds, cost/slippage sensitivity, MAE/MFE attribution, multiple-testing controls and Strategy Evolution integration.
