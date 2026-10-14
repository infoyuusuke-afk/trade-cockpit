# 100億PROJECT｜Issue #382：Collectorクリティカルパス分離のWindows合成実証

**DRAFT / SYNTHETIC ONLY / OWNER PC UNTOUCHED**。起点main `faf4540260e0d91dc28484480304e99e36f2d7d7`。PR #381（head `675ba07888b81ac3fb666632cee433f41777923c`）は有限のCSV例外に対応したが**同期ディスク待ちをなくしていない**。本PRはCollector本体を触らず、停止要因の証拠と隔離の設計試験を用意する独立新規Draft。

## 1. なぜCSVだけ非同期化しても完成しないか

実コードの監視中`while ($true)`には以下が混在している。

| ブロック要因 | 実装の例 | 未解決のリスク |
|---|---|---|
| 9種類CSVの同期追記 | `Add-Content` ／PR #381 `Invoke-MS2SafeCsvAppend` | 部分追記/書込失敗/ディスク永久ブロック／後続signals影響 |
| 毎周期フォルダー・ヘッダー | `New-Item`, `Ensure-Csv` | FSが遅いとtick取得前に停止 |
| JSON/HTML更新 | `Write-AtomicUtf8`, `[IO.File]::WriteAllText`, `Move-Item` | JSON読者ロック・tempの未確定・retry待機。5回×最大4待ち×150ms＝**retryだけで600ms** |
| 各種履歴/評価の保存 | `Write-CsvObjects`,`Write-ImmutableJson`,`Get-FileHash` | 引け処理と監視/停止状態が同じループを占有 |
| Excel COM操作 | `Invoke-ExcelCom` default Retries=240, DelayMilliseconds=250 | 250ms×最大239回≈59.75秒の**設定上のsleep**。COM呼出自体の待ち時間は別途不明。60秒停止したと実測したわけではない |
| 外部取得・音声 | `Get-Utf8WebContent`,`Invoke-SerializedSpeak` | 呼出しスレッドでの同期待ちの可能性、頻度・OS最悪時間未検証 |

これらは**ソース上の停止可能性**の棚卸しであり、実機障害が何回起きたか・マーケットtickが何件失われたかはUNKNOWN。

## 2. 最小の分離アーキテクチャ

**A: Price/Signal/Risk Lane**：取得した市場値の元のmissing, observation_time, available_at, session+poll IDを決定。現に観測不能なときはDEGRADED/NO_TRADE。価格/監視/停止状態更新は、可能な限りWriterとは無関係に進める。Excel COM取得はなおAに残る可能性があるため、このフェーズの合格は全体の停止回避を意味しない。Excel COMについては専用thread/process隔離と取得期限・stale判定を**別設計**で検証する。

**B: Bounded Producer→Worker**：precreate/prewarm/preallocateした有界インメモリ共有領域に、一定サイズの入力だけを TryOffer (0 wait) する設計。enqueue前にJSON serialize・SHA・disk write・process open/attachなどは行わない。queue-full/locked/STOP/DEAD/KILLでは理由付きDROP。誤った自動再送なし。Producerに直接writerのfsync/スレッドjoin/cancel不能I/Oを行わせない。固有session/generation/poll IDとsource timestampがない既存CSVを巻き戻して再ラベルしない。

**C: Durable Writer Evidence Lane**：事実の`QUEUED`、`PERSISTENCE_CLAIM`、独立fsync+readbackが証明された`PERSISTED_VERIFIED`、`DROPPED_PRE_QUEUE`、`UNKNOWN_TERMINAL`を分離。実のwriterが停止・再起動・ディスク障害時に`UNKNOWN`を補完しない。private市場/口座データはpublic GitHubに保存しない。

既存のunmerged PR #347–#373にはWindows IPC、PowerShell native bridge、Windows Process/Write Queue、#367 isolated ingress、#369 DROP、#371 ledger、#373 native concurrentがあります。**既存資産を利用し、全14本を一括マージせずにRelease Cutを設計する**。#379の観測と受付契約も再利用する。過去計測でnative cold/tail/最大5msは未達・同一user認証未解決。閾値を変えて成功扱いしない。

## 3. 今回実行するWindows 5.1合成隔離試験

`tests/ms2_writer_process_isolation_synthetic.ps1`：Windows PowerShell 5.1で親Producerと`Start-Job`による**別プロセス**Workerを生成。親が作成した名前付きMemoryMappedFile＋Mutexの4スロットbounded ringを事前attach、子が取出す。投入は`WaitOne(0)`で待たず、状態をQUEUED／QUEUE_FULL／GATE_BUSY／ABANDONED／CORRUPTへ分類する。子の「正常consume」「Writerの外側で4秒Sleep」「gate保持の4秒Sleep」「kill/worker停止」「queue full」を再現。

**重大な注意**：このringとPowerShell/C#コードはあくまで**使い捨てのsynthetic fixture**、実Collector adapter・identity authenticated IPC・本番Writerではない。実際の書込/fsyncや市場入力は存在しない。取込成功＝QUEUEDのみ、永続化確認にはならない。`Start-Job` startup/compileを計測外のprepとし、各poll TryOfferについてN、p50/p95/p99/max、accepted/drop分類、合成price/signal/risk/kill counterを出力。観測遅延の非同期境界とLinux/Windowsの差を混同しない。**Mutex.WaitOne(0)はOSのスケジューリング上のbounded WCETを保証しない**。最大5msを満たせなければ明示NOT METとする。シナリオで全pollの価格・signal/risk/kill mockが進んでも、実Collectorの音声やMS2 Excel COMが継続する証拠ではない。

`scripts/ms2_collector_critical_path_inventory.py`：GitHub内の公開Collectorのソースシグネチャを件数化。PowerShellパーサそのものではなく、リファクタでシグネチャが消えてもPASS判定にならない。

## 4. 受入禁止・次の実装ゲート

- 今回は**Collector/Watcher本体・Owner PC・Excel/MarketSpeed II・実レコード・main・RssOrder/実注文を一切変更・操作しない**。コードは合成・静的試験のみ。
- キル/unknown時のBroker自動再送、閾値緩和、real submit path本番配線禁止。
- サンプルは合成process/harness Nで、実市場適格N=0。EV、PF、DD、費用差引利益、100億残額はUNKNOWN。
- `real_submit_allowed=false`, `promotion_eligible=false`, `statistical_edge_confirmed=false`。
- 次の実装承認条件は「Collectorのどの同期I/Oをどのプロセスへ移すか」「現在のUI互換性とExcel稼働条件」「ACK/永続状態証拠」「Windows実機W1-W4検証」の分割Acceptance計画。実Collector改修・owner実機テストは別途明示承認。
- CI内で失敗したら、再実行のGreenで過去のFAILを隠さず原因を記録する。合成PASSもP0本番BLOCKEDのまま。