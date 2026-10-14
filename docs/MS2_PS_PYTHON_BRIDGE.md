# PowerShell から Python への固定長受け渡し（未接続）

この文書は Issue #354 の接続契約である。Watcher `ms2_live/Kioxia_RSS_Live_Watcher.ps1` は変更していない。2秒ループへは入れてない。自動起動もしない。Windows の所有者PCでは未実施であり、ここには合格を書かない。

## 境界を越えるもの

越えるのは、すでにメモリへコピー済みの板を詰めた **2048バイトのレコード1件**だけである。銘柄、市場、`poll_seq`、取得元、最大10段の値段と数量、呼び出し側が測定済みの時刻、ギャップ診断が含まれる。Excel のハンドル、COM、JSON 文字列、パイプは渡さない。

`poll_seq` はループの通し番号であり、取引所の約定順ではない。逐次のセル読取なので `snapshot_atomic` は false のままである。`event_time` と `available_at` は、呼び出し側が測定していないとき空のままにする。数量が欠けている段は null のままで、0 にしない。

## 所有者

名前付き共有メモリを作るのは、ループの外で一度だけ起動した Python プロセスである。PowerShell は既存の名前を開くだけである。名前が無ければその場で `ATTACH_FAILED` を返し、待たない。再試行はしない。開く候補は渡された名前、`Local\` 付き、`Global\` 付きの3つまでで、繰り返さない。

ホットパスは `scripts/ms2_ps_python_bridge_producer.ps1` の `Submit-Ms2PsBridgeRecord` である。2048バイトをスロットへコピーし、書き込み位置を1進める。キューは8件で固定する。満杯のときは入ってきた側を捨て、`DROP_NEWEST` と数える。ファイルロック、`ConvertTo-Json`、インタプリタ起動、COM はこの関数に無い。

## Python の起動

2秒ループから `python.exe` を起動しない。起動確認はループの外の1回で、時間上限があり、失敗しても繰り返さない。インタプリタが無い、すぐ終了する、応答しない、のどれでも Watcher 側の関数は待たずに戻る設計である。ただし、その関数を Watcher へ結ぶ変更は入っていない。

オフラインの JSONL Writer は Windows でも import できる。モジュール先頭の `fcntl` は外した。既に詰めた 2048 バイトは `persist_bridge_record` が受け、Watcher も共有メモリも開かない。spawn する handoff ワーカーは今も `fcntl` を import するので、そのプロセス起動は Windows では **P0_BLOCKED** のままである。`SharedMemory.unlink` は Windows では何もしない。電源断への耐性は未検証である。所有者PCでの合格は書いていない。

起動方式は `spawn` だけを使う。`fork` で親のメモリを引き継ぐ前提は置かない。

## 停止

停止要求のあと 0.25秒を超えたら子プロセスを切る。キルスイッチはフラグ1つで、次の提出は待たずに捨てる。再起動時、未公開の一時ファイルは隔離し、再生しない。所有者PCのスリープ復帰は **NOT_VERIFIED** である。

## 証拠

stale、gap、時刻の矛盾、重複は閉じた取引に上げない。`close_state` は `NOT_CLOSED` のままである。合成入力と、Watcher がまだ書いていない実観測は混ぜない。実観測の適格件数は 0 のままである。

`real_submit_allowed`、`promotion_eligible`、`statistical_edge_confirmed` は false のままである。

## Windows で未実施

- 所有者PCでの W1 から W4
- 所有者PCでのスリープ復帰
- 現在値、音声、売買サインの実行時影響（ソースが同じことだけ確認し、実行はしていない）
- 市場が開いているときの COM 競合

GitHub の `windows-latest` で合成レコードの開閉ができても、所有者PCの Watcher へ接続できたことにはしない。
