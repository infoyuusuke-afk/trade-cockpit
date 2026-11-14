# trade-cockpit STATUS

最終更新: 2026-10-18（GitHub mainを開発・進捗共有の唯一の正本とする）

このファイルは短い入口です。現在の状態・工程・決定事項は、次の正本ドキュメントに書かれています（この順に読む）。

1. [docs/MASTER_PROJECT_STATE.md](docs/MASTER_PROJECT_STATE.md)：現在の状態、経済指標、役割、安全ルール
2. [docs/CURRENT_WBS.md](docs/CURRENT_WBS.md)：工程表（P0-1〜P3）と各PRの状態
3. [docs/DAILY_PROGRESS.md](docs/DAILY_PROGRESS.md)：日々の進捗
4. [docs/DECISIONS.md](docs/DECISIONS.md)：正式な決定事項（D-001〜）
5. [docs/AI_COCKPIT_MASTER_SPEC.md](docs/AI_COCKPIT_MASTER_SPEC.md)：目標アーキテクチャとフェーズゲート
6. Issue #282 の最新 `[100B_COORD_V1]` 記録：詳細な判断履歴。上の文書より新しい正式判断は、`main` に反映するまで `PENDING_DOC_SYNC` として扱う（優先順位と反映手順は DECISIONS.md D-022）。

## 今の要点（2026-10-18）

- 現実の紙幣：未確認。Project純損益と100億円までの残額：UNKNOWN（UNKNOWN は 0 ではない）。
- V10 の完成形：AI が最大限自動化し、OWNER は最終承認だけを行う（D-020）。実注文は禁止のまま。
  - `REAL_SUBMIT_ALLOWED=false`、`STOP_ALLOWED=false`、`CUTOVER_ELIGIBLE=false`。
- 最優先は P0-1：V10 localhost セキュリティの修正（Draft PR #441）。
  - 旧 HEAD `1eb6dd5` の独立監査は CONDITIONAL PASS。指摘3件を GPT が修正し、新 HEAD `44f417a` の合成 CI は 9/9 PASS。
  - 新 HEAD の独立再監査は未実施。Draft・未マージで、OWNER の Windows 実機では未検証。
- V10 本体は `main` に未統合（Draft PR #438、#439、#440、#441）。実機受入は P0-27 の ADMISSION で BLOCKED。次は Issue #408（非停止の診断）。

## 運用ルール

- 新しいセッションは、必ず `main` の上記文書と、関連する Issue/PR を確認してから作業する。古いチャットの役割分担や進捗は正本として扱わない。
- 共有すべき完了事項、未解決事項、Owner の判断待ちは、該当する正本文書または関連 Issue/PR に反映する。`main` に反映していない作業は「共有済み」と扱わない。
- 1つの PR や同じファイル群を、複数の AI が同時に編集しない（D-017）。

## 履歴

2026-09-24 までの詳細な作業ログ（旧 STATUS.md の全文）は、[docs/history/STATUS_ARCHIVE_UNTIL_2026-09-24.md](docs/history/STATUS_ARCHIVE_UNTIL_2026-09-24.md) に変更せずに移しました。
