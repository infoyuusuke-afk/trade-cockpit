# 100億PROJECT — MASTER PROJECT STATE
Updated: 2026-10-18 JST
Status: ACTIVE
Authority: Canonical cross-agent project state (main). Detailed decision history: Issue #282 `[100B_COORD_V1]` records.

> 2026-10-18: this file was first created on 2026-10-08 on the unmerged V10 branch line (from PR #292) and never reached `main`.
> This version brings it to `main` and replaces the 2026-10-08 content, which became out of date.
> Note in particular that the 2026-10-08 statement "V10 START/STOP acceptance PASS" is no longer the current state (see §2).

## MASTER MISSION
100億円を稼ぐシステムをAIと作る。
手段は固定しない。期待値・収益化速度・再現性・Owner労務削減を継続評価する。

## 0. 現実の紙幣 — 最上位KPI
このセクションを技術進捗より必ず先に読む。

- Project revenue actually received: **0円 confirmed (2026-10-08時点)／それ以降は未確認**
- Project realized trading profit: **未確認**
- Project operating cost: **未集計**
- Owner labor cost: **未集計**
- Project net P/L: **未確定。黒字化未達**
- Owner-reported historical trading loss before/alongside project: **3,500万円超**
- 100億円 target remaining: **UNKNOWN（100億円＋未集計のProject赤字）**
- Rule: 技術完成度を現実の利益として計上しない。紙幣・実現損益だけを収益KPIとする。UNKNOWNは0ではない。

## 1. Current target (formal decision COORD-V10-OWNER-FINAL-APPROVAL-20261018-V1)
V10の完成形は「AIが可能な作業を最大限自動化し、OWNERは重要な最終承認と例外対応だけを行う」。
- AIに任せる範囲（現段階）：データ取得、分析、候補選定、仮想注文案、安全検査、Shadow検証、事後評価、レポート作成。
- 自動実行しないもの（現段階）：実注文、実機切替、無承認マージ、有料契約、外部公開。
- 実発注は、将来、別途承認を受けた段階でのみ行う。

## 2. Confirmed state (2026-10-18)
- `main` には V10 本体（RUN / Controller / Gateway / BRAIN / STOP）がまだ統合されていない。V10 は複数の Draft PR に分かれている（CURRENT_WBS.md 参照）。
- V10 の実機受入は未完了。
  - OWNER実機 P0-27 は ADMISSION で BLOCKED（`PREFLIGHT_PORT_CHILD_IDENTITY_NOT_PROVEN`）。何も停止していない。
  - 次は Issue #408（P0-28：非停止の診断）。
- V10 の localhost セキュリティ欠陥（広すぎる CORS、静的ファイル配信の許可リストなし、Voice の GET 制御）は release-blocking P0 である。
  - 修正の Draft は PR #441。合成 CI は PASS。独立セキュリティレビューは未実施。
- AI候補 → 模擬OWNER承認 → Shadow の合成E2Eは PR #442（Draft、合成CI PASS）。
  - 本人認証、実市場データ、Shadow約定、期待値の証明はまだない。
- `real_submit_allowed=false`、`STOP_ALLOWED=false`、`CUTOVER_ELIGIBLE=false`。
- V8/V9 の本番実行経路は復活させない。

## 3. Known current gaps
- `owner_approval_queue.py` の `decided_by="OWNER"` は文字列の確認であり、本人認証ではない。
- 実市場データの利用権限が、データ源ごとに確定していない（DECISIONS.md D-019）。
- 正本ドキュメントが、main・V10系ブランチ・Issue #282 に分散していた（2026-10-18 に本PRで main へ一本化）。
- EVENT 5 / HOT銘柄は、まだ全市場のリアルタイムレーンになっていない（2026-10-08 以降、未解消）。

## 4. Architecture ownership (2026-10-18 formal decision)
- ChatGPT 統括（normal chat）：問題定義、優先順位、仕様、受入（Acceptance）、統合の唯一の権限。
- GPT 開発責任者：主たる実装担当。
- 専門アナリストGPT：需給・SQ、PRE-NEXT、Revenue Hunter。助言と分析のみで、注文の入力にはしない。
- Claude / Claude Code：独立監査と、統括が工程を指定した限定的な補助。Claude が主担当になることは前提にしない。
- Cursor：開発の前提にしない。
- Cloud / Work：PC・GUI・ブラウザ・ファイル操作が本当に必要な、範囲の決まった作業のみ。
- Owner：ほぼゼロ操作。必要な実機確認と最終承認のみ。
- 1つのPR、または同じファイル群を、複数のAIが同時に編集しない。

## 4.1 Mandatory handoff gate
Work / Cloud / Cursor / Claude などに作業を渡すのは、それらが使えるからという理由だけでは行わない。
統括は、渡す前に次をすべて文書で確定する。
1. 目的と経済的な理由
2. 確認済みの事実と未知事項
3. 入力データの出所
4. 必要な出力
5. 判定・計算の規則（該当する場合）
6. 安全条件
7. 受入条件（Acceptance / Definition of Done）
8. 次の作業の担当者

実行者は、凍結された指示書を受け取り、それを作り直さない。
実行者の出力は証拠にすぎない。統括が受入条件と照合し、正本を更新するまでは、プロジェクトの事実として扱わない。

## 5. Canonical runtime (V10)
- V10 本体は `main` 未統合。統合の正式な順序は CURRENT_WBS.md の P0-2 を参照。
- ポート：Collector 28580 / Gateway・UI 28581 / Watcher 28582 / Voice 28583 / BRAIN Gateway 28584。28584 は BRAIN observer プロセスではなく Gateway である。

## 6. Safety rules
- `real_submit_allowed=false`
- Excel を一括で終了させない。
- PowerShell を一括で終了させない。
- MarketSpeed II を強制終了させない。
- 強制クリーンアップは、PID の本人確認を厳密に行ったうえでのみ行う。
- 起動時に git の状態を変更しない。
- データの同一性が不確かな場合や、市場データが古い場合は fail closed とする。
- 公開リポジトリに、非公開の MS2 / Excel データ、認証情報、注文、個人の保有を載せない。
- モデルの予測を、自律的な売買注文に変換しない。

## 7. Mandatory reporting order
プロジェクトの進捗報告は、必ず次の順で始める。
1. 現実の紙幣
2. Project net P/L
3. 100億円までの残額
4. 今日の実現利益 / 売上
5. 今日の実費
6. Owner労務コスト
7. その後に、技術的な進捗、受入（Acceptance）、ブロッカー、次の作業

未知の値は「未集計」「未確認」と明記する。推測で埋めない。

## 8. Canonical documents (read in this order)
1. `docs/MASTER_PROJECT_STATE.md`（this file）
2. `docs/CURRENT_WBS.md`
3. `docs/DAILY_PROGRESS.md`
4. `docs/DECISIONS.md`
5. `STATUS.md`（短い入口。2026-09-24 までの詳細な履歴は `docs/history/STATUS_ARCHIVE_UNTIL_2026-09-24.md`）
6. `docs/AI_COCKPIT_MASTER_SPEC.md`
7. Issue #282 の最新 `[100B_COORD_V1]` 記録。この文書より新しい判断は、Issue #282 側が優先する。正本へ反映するまでは「未反映」として扱う。

`docs/AI_SHARED_SHEET.md` は、C-xxx 番号の履歴的な調整シートである。新しい判断は、DECISIONS.md と Issue #282 に記録する。
