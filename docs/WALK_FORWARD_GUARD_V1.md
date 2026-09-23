# Walk-forward Guard v1

Strategy Lab must validate chronologically. Training must end before each test window starts, and each out-of-sample fold must retain positive measured expectancy.

Because the research engine can examine many hypotheses, ordinary significance thresholds can create false discoveries. v1 applies a conservative Bonferroni adjustment using the number of hypotheses tested. This is a guardrail, not a claim that p-values alone establish trading edge.

Later versions should add embargo/purging where labels overlap, false-discovery-rate reporting, bootstrap confidence intervals and dependence-aware tests.

A PASS only allows progression to the next research gate. It never grants live-order permission.
