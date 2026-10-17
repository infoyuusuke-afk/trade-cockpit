# P0-33｜Mobile Control CIと旧V8/V9全件診断の分離

## 事実と非合格の証拠
2026-10-17 以前から `Mobile Control Tests` は `scripts/**` と `tests/**` の全変更で走り、約1,920件を無条件に実行していた。基準HEAD `90644b3690a389e1c65a35c16a361fea6a49dbdf` のrun [39004353176](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39004353176) も失敗。P0-32 run [39008530878](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39008530878) は `FAILED (failures=26, errors=89, skipped=165)`。少なくとも、現Checkoutから削除された旧 `AI_COCKPIT_CONTROLLER_V8.ps1` のFileNotFoundError、欠落V9 *.ps1 をpwshで実行したexit64/Usage失敗が含まれる。**全体回帰は未合格であり、本PRの修正で元の115件が合格したことにはならない。**

## 実装
- `.github/workflows/mobile-control-tests.yml` はモバイル承認、OWNER承認キュー、実行契約・実行権限・自律ゲートに関係するソースとテスト、EV/戦略データの変更のみで起動する。テスト6群は明示し、すべて実行。コマンドは `set -euo pipefail`、1件でもFAILならCIがFAIL。`real_submit_allowed=false` の既存アプリ実装は変更しない。
- `tests/test_mobile_ci_scope_contract.py` が必要なトリガー・全安全テスト呼出し・broad glob排除・fail-closed制約を検査。無関係な旧V8/V9を成功扱いしない。
- `.github/workflows/legacy-full-suite-diagnostic.yml` に、従来と同じ `python -m unittest discover -s tests -p "test_*.py" -v` の完全再現経路を**残す**。手動起動専用（費用・ノイズを抑制）、`continue-on-error` を使用せず、未解決FAILはFAILとして赤く表示する。

## 受入条件・禁止事項
Mobile専用CIのテスト全件がPASSし、仕様で固定した6群が欠落していないこと。Legacy 全件は依然未合格と明記する。個別の旧V8/V9欠落検査を修復する場合は別Issueで、削除された旧実行系の無断復元をしない。

OWNER実機は変更せず、停止・切替・Excel操作・実取引・GitHubマージ・課金禁止。P0-32のV2・固定配布PINは変更しない。
