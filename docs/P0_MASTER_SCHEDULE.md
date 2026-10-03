# 改訂 Master Schedule

日付は約束しない。旧 Baseline は残す。

## 旧 Baseline（書き換えない）

### 2026-09-18 MS2 安定稼働判定

`docs/MS2_STABILITY_REVIEW_2026-09-18.md` は、次の立会（文書は 2026-09-21 を想定）に、08:30 までの起動、09:00–09:15 の連続取得、引けまでの記録、発注 OFF を確認する、と書いた。この判定は「安定稼働未確認」のままである。

実績: その実機 Acceptance は 2026-10-03 時点でも PASS していない。2026-10-03 02:22:51 の専用ブック起動は重大エラーの確認で止まっている。

### 2026-09-22 Master Spec 第11節・第13節

`docs/AI_COCKPIT_MASTER_SPEC.md` は、工学の残りを Phase A–F、検証を複数の立会と数週間の forward 証拠とした。第13節の経路は PR 整理から Shadow Forward、校正、ルーター、長い Shadow、照合、Owner レビューである。

実績: main には Risk、Shadow、Fill Model、TradingView のギャップ分類が入った。最初の市場 I/O Acceptance は未 PASS。コードは前倒し、P0 の証拠は遅延。

## 改訂

| Gate | dependency | effort | earliest possible | blocking condition |
|---|---|---|---|---|
| G0 専用 Excel が開く | なし | 実機観測 1 回。追加の原因調査はしない | 次に Owner が専用ブックだけを開く立会 | 確認ダイアログが残っている。PID 43904 へは操作しない |
| G1 RSS が更新する | G0 | 同じ立会のセル観測 | G0 と同じ立会 | G0 FAIL |
| G2 Collector | G1 | 既存 Collector。照合は repo 済み | G1 の直後の payload | 実 payload が無い |
| G3 Gateway | G2 | 既存の拒否。正例は同じ payload | G2 と同時 | 拒否を弱める変更。しない |
| G4 五境界の一致 | G2 と MS2 表示 | harness 済み。表示の観測が残る | G2 の同じ時刻 | MS2 表示が bundle に無い |
| G5 確認前は再開しない | G4 の FAIL の次 | `evaluate_resume` 済み | 最初の不一致の次の束 | 印なし再開 |
| G6 実注文禁止 | なし | 維持 | 済み（リポジトリ） | `real_submit_allowed=true` を入れる変更 |
| P2 以降 | G0–G5 PASS | 今は見積もらない | G4 と G5 のライブ PASS のあと | 前 Gate の FAIL |

Owner 介入は G0 と G1 の実機だけを予定する。この Schedule の作成に Owner 時間は使っていない。
