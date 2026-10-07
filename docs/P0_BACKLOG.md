# P0 Backlog

依存順。G0–G5 を最短で PASS させるための列。effort は暦日ではなく作業範囲。

| Task | Gate | Owner | 実装内容 | Acceptance | blocker | effort |
|---|---|---|---|---|---|---|
| P0-01 | 全部 | 不要 | vNext、Matrix、Contract、資産表、Schedule を旧 Spec を残して追加 | 旧ファイル未改変。G0/G1 が PENDING と読める | なし | 文書のみ。この草案 |
| P0-02 | G2–G6 | 不要 | `scripts/p0_market_io_acceptance.py` と単体テスト。合成は `NOT_LIVE` | テストが、不一致・stale・実注文 true・印なし再開・証拠ファイル欠落を不合格にする | なし | 純粋関数とテスト。この実装 |
| P0-03 | G0 | 必要 | 専用ブックが確認ダイアログなしで開く | Matrix G0 | 表示中ダイアログ。追加調査はしない | 次の立会の実機観測 1 回。コマンドは今出さない |
| P0-04 | G1 | 必要 | RSS セルが実市場値で更新される | Matrix G1。生値は repo に置かない | P0-03 | 同じ立会の観測 |
| P0-05 | G2 | 必要（取得）/ 不要（照合） | 到着した `live_ms2.json` を harness にかける。Collector の挙動は変えない | G2 が実束で PASS、合成では NOT_LIVE | P0-04 | 既存 Collector。変更は不一致が出てから |
| P0-06 | G3 | 不要（拒否）/ 必要（正例） | Gateway の拒否は既存テストを正とする。正例は実 payload の一致 | 拒否を弱めない。正例は G2 と同じ束 | P0-05 | 既存 Gateway。増築しない |
| P0-07 | G4 | 必要 | MS2 表示値を、価格と時刻だけの私的観測として harness の `ms2_display` に渡す経路を、実観測の形式だけ先に固定する | 5 境界の fingerprint 一致。表示が欠ければ FAIL | P0-04。画面の読み取りは Owner | 形式は Contract 済み。取り込み実装は実観測の形が決まってから |
| P0-08 | G5 | 不要（規則）/ 必要（実再開） | `evaluate_resume` を、FAIL の次の束に使う | 印なしは FAIL。合成は NOT_LIVE | P0-07 の FAIL が一度あること | 関数は実装済み |
| P0-09 | G6 | 不要 | 変更しない。`real_submit_allowed=false` | フラグが true の束は FAIL | なし | 監視のみ |
| P0-10 | G2–G5 | 不要 | `run_acceptance`。既存ファイルだけを照合し、入力ハッシュと判定を evidence JSON に残す。価格は evidence に写さない | ファイルが無い Gate は NOT_RUN。合成は NOT_LIVE。G0 ファイルが無ければ PENDING | 実ファイルは未着 | 純粋関数。実装済み |
| P0-11 | G0 G1 | 必要 | 観測ファイル `g0_observation.json` / `g1_observation.json` は Runner が作らない | Owner の起動結果がファイルとして残ったときだけ PASS/FAIL | ダイアログ残留。操作は依頼しない | 判定口だけ実装済み |
| P0-12 | 時刻 | 不要 | RSS セル日付以外を絶対時刻にしない | `quote_date_source=rss_cell` だけ VERIFIED。現状の公開 JSON にはその項目が無い | Collector は日付を保存していない | 調査と判定は実装済み。Collector 変更は根拠がセルに残ってから |

P0-03 と P0-04 だけが `OWNER ACTION PENDING`。他の Task は、実束が来るまで照合器と契約の側で進める。
