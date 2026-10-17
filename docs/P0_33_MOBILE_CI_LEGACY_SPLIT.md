# P0-33｜Mobile Control CIと旧V8/V9全件診断の分離

## 統括判断（2026-10-17）
修正方針①を正式採用：廃止済みV8/V9に依存する旧テストだけを通常CIから除外し、V10を含む現行テストは全件維持する。旧テストは削除せず手動診断workflowに残す。

## 事実
- 2026-10-08 のコミット a9633f58 / fdcbdaff / e29fa830 でV8/V9スクリプトを削除（D-003）したが、それを読むテストが残った。
- Mobile Control Tests run [39037387387](https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39037387387)：`FAILED (failures=26, errors=89)` の115件は、すべて削除済みV8/V9ファイルの FileNotFoundError、またはpwshが存在しないV9スクリプトを受け付けない（exit 64）もの。
- **115件は未修復であり、合格扱いではない。**

## 実装
- `.github/workflows/mobile-control-tests.yml`：従来どおり `scripts/**`・`tests/**` 等で起動し、`scripts/ci_mobile_current_suite.py` で全テストを実行する。
- `scripts/ci_legacy_v8_v9_excluded.txt`：除外するテストIDを115件に固定（モジュール単位ではなくテストID単位。同じファイル内の現行テストは実行される）。
- `scripts/ci_mobile_current_suite.py`（fail-closed）
  - 除外できるのはリストにあるIDだけ。
  - そのテストのモジュールが「存在しないV8/V9スクリプト」を参照していなければ失敗する（V8/V9が再導入されたら除外も無効になる）。
  - V10という名前のIDは除外できない。
  - モバイル承認・注文安全の6群が無ければ失敗する。
  - 残りのテストに失敗が1件でもあればCIは失敗する。
- `tests/test_mobile_ci_scope_contract.py`：上記を静的・合成的に検査する。
- `.github/workflows/legacy-full-suite-diagnostic.yml`：従来と同じ全件実行を手動起動専用で残す。`continue-on-error` は使わず、115件はREDのまま表示される。

## 注意
- `test_ai_shadow_supervisor...test_controller_and_gateway_keep_real_submit_locked` はV9のController/Gatewayで実注文ロックを確認する旧テストで、除外対象に含まれる。V10の実注文禁止は別のV10テストで担保する必要がある。
- OWNER実機の変更・停止・切替・Excel操作・実取引・マージ・課金はしない。`REAL_SUBMIT_ALLOWED=false`、`STOP_ALLOWED=false`、`CUTOVER_ELIGIBLE=false`。
