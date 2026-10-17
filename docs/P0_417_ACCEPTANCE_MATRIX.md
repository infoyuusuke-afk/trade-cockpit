# P0-417 | 現行V10・旧V8/V9履歴・非停止V2の検収責務

**MASTER MISSION:** 100億円の費用控除後・累積実現純利益。現時点で実取引証拠や市場データの鮮度を証明していない。

## なぜ分離するか
`Mobile Control Tests` はUbuntuで `tests/test_*.py` 全域を単一実行するため、削除済みV8/V9ソースを参照する旧テストが失敗する。元の全域CIはFAILのまま維持。旧テストをスキップ/除去したり、共通CIを無効化して偽PASSにしない。専用matrixは**別の明示的な検収項目**を検証するもので、全体の代わりではない。

## 4つの独立ジョブ（`.github/workflows/p0-417-acceptance-matrix.yml`）

| job | 対象 | 成功の意味 |
|---|---|---|
| `v10-current` | 現行Collector＋V10 Controller、Windows合成セルフテスト | 現行コードのWorkbook同一性・誤銘柄・発注禁止の契約。実機ライブPASSではない |
| `legacy-v8-historic` | 固定履歴 `b81b8877b12a33368e91e5e156a2fc7ac4529349`、旧V8安全契約43件 | **歴史時点の**V8契約だけ |
| `legacy-v9-historic` | 同じ固定履歴、旧V9 Collector6件＋診断71件、Windows合成 | **歴史時点の**V9契約だけ。Git blobの元バイト列以外は拒否 |
| `v2-readonly-synthetic` | P0-32 V2独立検収5+7件 | 旧V10ファイルのmtime-only三点一致判定が合成環境で安全に動くことだけ |

## リリース判定

- `MATRIX_SYNTHETIC_PASS`: 上記4ジョブがすべてPASS。合成・過去ソースの限定検収に限る。
- `MONOLITHIC_CI=FAIL`: 旧V8/V9欠損/PowerShell環境誤適合等の全域CIのFAILは残る。完了・解決扱い禁止。
- `INDEPENDENT_REVIEW=PENDING`: P0-32には別担当者によるレビューなし。自己COMMENTEDをAPPROVEとして扱わない。
- `OWNER_V10_RUNTIME=BLOCKED`: V2実機read-only検収未実施。旧V1 P0-31のBLOCKEDを解除しない。
- 常に `STOP_ALLOWED=false`, `CUTOVER_ELIGIBLE=false`, `REAL_SUBMIT_ALLOWED=false`。実停止、再起動、実注文、Excel操作、PR自動マージ、本番導入不可。

## 次の根本改修
現行各機能に正規の契約テストを追加する。旧テスト群は履歴専用のまま保存し、全域テストが現行CIへ混在し続ける問題は検査件数を監査できる移行設計の承認後に解消する。旧障害数を上書きするだけの改修はしない。
