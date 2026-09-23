# C-195 International UI & Content Contract

## Principle
Trading logic and facts are language-neutral. Presentation is a separate layer.

### Modes
- `OWNER_JA`: Japanese-first operational UI and voice. Owner approval never requires English.
- `BROADCAST_EN`: English-first public content for overseas investors interested in Japanese equities.
- `BILINGUAL`: Japanese + English for review and QA.

## Overseas editorial frame
Primary series: **TOKYO CLOSE → WALL STREET**

The post-close package answers:
1. What happened in Tokyo?
2. Which Japanese stocks/sectors mattered?
3. Which observations may be relevant context for the coming U.S. session?
4. What should be watched next?

Do not turn correlation into causation or state a U.S. market direction as fact.

## Canonical event keys
UI copy is derived from stable keys, never from trading logic.

| key | OWNER_JA | BROADCAST_EN |
|---|---|---|
| rapid_adverse_move | 急落警戒 | Sharp Drop Alert |
| vwap_reclaim | VWAP回復 | VWAP Reclaim |
| or5_low_reclaim | OR5安値を奪回 | OR5 Low Reclaimed |
| cautious_new_long | 新規ロング慎重 | Caution on New Longs |
| relief_exit_risk | 安堵利確注意 | Relief-Exit Risk |

Unknown keys fail closed and must not invent copy.

## Character starting roles
These are original working roles and may be revised from audience data.
- ムギ: human-trader emotion and momentum.
- メル: calm market-structure explainer.
- くうちゃん: risk-control / invalidation check.
- ハム: data/research voice; MAE/MFE/OR/VWAP facts.

No character is permanently the fool or villain.

## Publication guard
Generation is not publication. External publication always remains a separate Owner approval action.
