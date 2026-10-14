# Windows向け private JSONL Writer（オフライン）

この文書は Issue #357 の保存手順である。Watcher `ms2_live/Kioxia_RSS_Live_Watcher.ps1` は変更していない。自動起動もしない。所有者PCの W1–W4 は未実施であり、ここには合格を書かない。

## 何を保証するか

単一の Writer が `data/private/ms2_sidecar/<file>.jsonl` を持つ。ロック待ちはしない。POSIX は `flock` の非待機排他、Windows は `LockFileEx` の非待機排他である。Windows のモジュール読込は `fcntl` を使わない。

一時ファイルは公開ファイルと同じディレクトリに作る。書込、`fsync`（Windows では `FlushFileBuffers`）、読戻しのあとで同じディレクトリ内の置換をする。置換前にプロセスが止まると、公開済みバイトは残る。残った一時ファイルは次の起動で隔離し、公開ファイルへ混ぜない。壊れた JSONL は修復しない。

`directory_fsync` は POSIX の置換成功時だけ行う。Windows には同じディレクトリフラッシュが無い。電源断に耐えることは検証していない。報告の `power_loss_durability` は `NOT_VERIFIED` のままである。

## 接続しないもの

既定は無効である。2048バイトの既存ブリッジレコードは `persist_bridge_record` がオフラインで受け取る。共有メモリ、パイプ、Excel、Watcher は開かない。handoff のワーカーは引き続き `fcntl` を import するため、Windows では起動しない。状態は `P0_BLOCKED` である。

`sequence_basis` は `POLL`、`snapshot_atomic` は false のままである。未測定の `event_time` と `available_at`、欠損数量は null のままである。stale、gap、重複、不正時刻、不正数量は `CLOSED` にしない。

## 所有者PC W1–W4（未実施）

市場が閉まっている時間に、別承認のあとでだけ行う。このリポジトリの Actions は実行しない。

1. W1: sidecar フラグ無しで現行 Watcher を起動する。private JSONL が増えないこと。現在値、音声、サインが更新されること。
2. W2: フラグを付けたオフセッションで、既存の40回のセル読取に1回の fsync を足したポーリング間隔を記録する。private ファイルはアップロードしない。
3. W3: Ctrl+C で止める。`RSS接続!B16` が停止になり、Excel は開いたままであること。Excel の強制終了は失敗である。
4. W4: COM エラー、サイン凍結、ポーリング欠測、sidecar 例外ではフラグをオフにし、監査済み Watcher に戻す。

中止と復旧は `docs/MS2_NONBLOCKING_HANDOFF_W1_W4.md` と同じである。壊れた sidecar は追記せず、必要なら隔離コピーだけを private 配下に残す。tick ログと気配値ログは消さない。

`real_submit_allowed`、`promotion_eligible`、`statistical_edge_confirmed` は false のままである。実観測の適格件数は 0 である。
