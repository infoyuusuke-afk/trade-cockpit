# P0 Asset Map

分類は 2026-10-03 の監査。ファイルは再利用の単位。

## KEEP

| モジュール | 再利用 |
|---|---|
| `ms2_live/MS2_RSS_100_Collector.ps1` | RSS から `live_ms2.json` を書く。P0 の Collector |
| `downloads/AI_COCKPIT_GATEWAY_V9.ps1` | stale / mismatch を拒否し、`real_submit_allowed=false` |
| `downloads/AI_COCKPIT_CONTROLLER_V9.ps1` | 起動と fail-closed。他 Excel を殺さない。ダイアログを押さない |
| `downloads/EXCEL_IDENTITY_PROBE_V9.ps1` | 別 PID を採用しない |
| `scripts/signal_contract.py` | 鮮度と NO TRADE。Strategy 接続は P2 まで増やさない |
| `scripts/risk_gate.py` | P2 の資産。今は触らない |
| `scripts/ai_shadow_supervisor.py` | P3 の fail-closed。増築しない |
| `scripts/p0_market_io_acceptance.py` | 到着済みの束を照合する。この再基準化で追加 |

## MODIFY

今は挙動を変えない。G0 が PASS したあとに、成功条件だけを合わせる。

| モジュール | 変更点 |
|---|---|
| `downloads/AI_COCKPIT_CONTROLLER_V9.ps1` | 成功を「専用ブックが開き RSS が更新する」に戻す。共存の完成は目標にしない |
| `ms2_live/MS2_RSS_100_Collector.ps1` | `source_timestamp` が `HH:mm:ss` である事実を契約で明示済み。絶対時刻への変更は、G1 の実値を見てから |
| Strategy 入力 | 明示の quote 射影だけを読む。対象スクリプトは P2 で、P0 の PASS 前に接続しない |

## DEFER

| モジュール | 理由 |
|---|---|
| `downloads/DIAGNOSE_CANONICAL_*.ps1` | Excel 追加調査。停止 |
| `downloads/CLEAR_CANONICAL_WORKBOOK_RECOVERY_V9.ps1` | 再実行しない |
| `downloads/RESTORE_CANONICAL_WORKBOOK_RECOVERY_V9.ps1` | 再実行しない |
| `downloads/AI_COCKPIT_VOICE_BRIDGE_V9.ps1` | P5 |
| `card_system.js` と `tests/card_system.test.mjs` | P5。tests 15 / 19 は市場 I/O の Gate に数えない |
| `scripts/strategy_router.py` `scripts/strategy_evolution.py` `scripts/strategy_research_engine.py` `scripts/strategy_validation_lab.py` | P2 / P4 |
| `scripts/shadow_execution.py` `scripts/shadow_fill_model.py` `scripts/shadow_forward_*.py` `scripts/shadow_position.py` | P3 / P6 |
| `scripts/journal_projection.py` | P5 |
| `scripts/local_market_data_gateway.py` | 研究用。V9 Gateway の正本ではない |
| 一般 Excel との共存を増やす Controller 変更 | 後工程 |

## MISSING

| 欠落 | Gate |
|---|---|
| 専用ブックがダイアログなしで開いた実観測 | G0 |
| RSS 実市場値の実観測 | G1 |
| MS2 画面値を quote として残す私的な観測形式の実適用 | G4 |
| 境界をまたぐ単調 sequence | Contract の fingerprint で代用中 |
| 立会をまたぐ連続性の実測 | G1 のあと |
