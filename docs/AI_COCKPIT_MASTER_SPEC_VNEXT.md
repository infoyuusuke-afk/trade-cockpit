# AI Cockpit Master Spec vNext（草案）

Status: DRAFT。2026-10-03 の監査を、100億PROJECT / AIコクピット再基準化の入力にした。  
この文書は `docs/AI_COCKPIT_MASTER_SPEC.md`（2026-09-22、checkpoint `1e856eeacdf71006fa095da27e1aa6e46862fb7b`）を置き換えない。旧 Baseline はあのファイルのまま残す。

PR #292 は Draft / unmerged のまま。`real_submit_allowed=false`。

## Mission

100億円を稼ぐシステムを AI と作る。手段は固定しない。期待値の高い手段を探索し、検証し、実行し、改善し、再投資する。

AIコクピットは現在の最重要 Trading Engine であり、100億PROJECT そのものではない。より期待値の高い AI、サービス、収益 Engine が確認されたら採用候補にする。

Owner の時間と資金は有限である。Owner の操作時間は PROJECT COST である。Owner がいないと開発が止まる構造は、改善対象である。

## 現在の P0

正確で fresh で連続した実市場データ。

```text
MarketSpeed II → MS2 RSS → RSS専用Excel → Collector → Gateway → Strategy Input
```

この経路が FAIL のあいだ、Strategy / AI SHADOW / UI / Voice / Execution の追加増築はしない。既存資産は捨てない。

一般 Excel と RSS 専用 Excel のザラ場中の共存は、必須要件から外し、後工程へ DEFER する。無関係な Excel を止める実装にはしない。ダイアログを自動で押さない。

OfficeFileCache / Rules / Recovery / OAlerts / Event ID 300 / DisabledItems の追加原因調査は停止する。PID 43904 と表示中のダイアログには追加操作しない。

## 旧 Baseline との差分

| 項目 | 旧 Baseline（2026-09-22 Master Spec） | vNext |
|---|---|---|
| 最終目的 | 日本株の再現可能な AI コクピット | 100億PROJECT。コクピットはその現在の Trading Engine |
| 優先順位 | survive、資本保全、決定性、監査、fail-closed、その後に期待値 | 同じ安全順を維持したうえで、現在の P0 は市場 I/O |
| クリティカルパス（第13節） | PR 整理 → データ意味 → Shadow Forward → 校正 → ルーター | G0 専用 Excel → G1 RSS → G2 Collector → G3 Gateway → G4 一致 → G5 確認後再開 → G6 実注文禁止 |
| Excel | MS2 RSS の橋。共存の成否は未記載 | 専用ブックの単独起動が P0。一般 Excel との共存は DEFER |
| 進捗の単位 | 実装と証拠。テスト数だけでは done ではない | Acceptance の PASS 数。commit 数は進捗ではない |
| 実注文 | HOLD。明示承認まで無効 | 変更なし。`real_submit_allowed=false` |
| 安全 | stale / missing / 破損は fail-closed。壊れた状態を黙って修復しない | 変更なし。弱めない |

2026-09-18 `docs/MS2_STABILITY_REVIEW_2026-09-18.md` の「次の立会日に実機確認」は未達のまま残す。日付を書き換えて遅延を消さない。

## 開発順序

```text
P0 専用 Excel と市場 I/O
  → P1 Realtime Data Pipeline の一致
  → P2 Strategy / Risk
  → P3 AI SHADOW 実市場運転
  → P4 Strategy Evolution
  → P5 UI / Voice / Journal
  → P6 Execution DRY-RUN と注文・約定・Position 照合
  → P7 Controlled LIVE（別の明示承認まで HOLD）
```

前の Gate が FAIL のあいだ、後の工程を増築しない。

## この草案が指す文書

- Acceptance: `docs/P0_ACCEPTANCE_MATRIX.md`
- 契約: `docs/P0_DATA_CONTRACT.md`
- Backlog: `docs/P0_BACKLOG.md`
- 資産: `docs/P0_ASSET_MAP.md`
- Schedule: `docs/P0_MASTER_SCHEDULE.md`
- 照合 harness: `scripts/p0_market_io_acceptance.py`

G0 と G1 の実機 Acceptance だけが `OWNER ACTION PENDING` である。この草案の作成に Owner 操作は要らない。
