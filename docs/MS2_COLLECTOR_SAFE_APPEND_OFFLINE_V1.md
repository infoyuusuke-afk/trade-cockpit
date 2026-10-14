# Issue #376｜MS2 Collector 本体・有限保存エラー隔離の最小修正（OFFLINE Draft）

**2026-10-15 JST / AUTHORISED SCOPE: SOURCE PATCH & SYNTHETIC TEST ONLY.**
起点main：`faf4540260e0d91dc28484480304e99e36f2d7d7`。
Issue #376 OWNER「承認」は**Collectorのオフライン修正Draft PR**の作成のみを認めた。OWNER PC起動/停止・本番適用・MS2/Excel接続・private CSV読取・mainマージ・RssOrder等の実注文は一切承認されていない。

## 今回実際に直したもの／直していないもの

1. `ms2_live/MS2_RSS_100_Collector.ps1` を実際に変更。従来の9つの `Add-Content` 呼び出しを、`Invoke-MS2SafeCsvAppend`へ集約。通常は既存CSV行と出力パス/順序を保持したまま `Add-Content -LiteralPath ... -Encoding UTF8 -ErrorAction Stop` を実行。有限の例外発生時、例外やprivateパスをログへ出さず、`ms2RecordFaulted=true`, `recording_degraded=true`、固定stream名と匿名エラー件数のみを保持する。
2. 部分appendの恐れがあるため、そのセッション内で**再試行・UNKNOWN自動再送を禁止**。次の呼び出しは即falseを返す。 `seenTicks`・`creditSaved`・`loggedSignals`の記録済みフラグはappend成功時のみ更新する。成功と記録済みを混同しない。
3. price/volume/vwap/quoteのうちnullになった**10項目の名前を、0への既存fallbackの前に観測**。`source_missing_fields`と`source_quality`を新しいJSONの対象銘柄の別metadataとして残す。**CSVのcanonical headerと過去ログ/2038-byte等の既存record/hashセマンティクスを変更しない**。legacy `null→0`の既存数値fallbackは互換性を維持したが、AI研究側はその0を観測済み0として認証禁止。
4. 保存エラー、または当該銘柄に10項目の観測欠測がある場合は買い/空売りのシグナルを`データ品質不明・売買禁止`へ降格。保存エラー後は`$results`全件のactionableシグナルを抑制し、持越し新規候補も作らない。ここでの`real_submit_allowed`は常にfalseであり、シグナル抑止以外の注文経路を追加しない。

**重要な未達**：
- これは**同期ディスクI/Oを使用した有限エラー隔離**。停止不能I/O、遅いdisk write、PowerShell COM/Excel update待ち、process死、電源断のときprice/voiceが継続する保証はない。前工程で要請された**完全な非ブロッキング隔離Writerは未実装・P0 BLOCKED**。P99/最大5msはNOT VERIFIED、ましてMETではない。
- `Ensure-Csv`, directory作成、`Write-AtomicUtf8`, hold/history/stats等、9つの`Add-Content`以外の同期書込が多数残る。**監視全体の障害隔離完了と主張禁止**。
- appendの成功returnはOS/ファイルAPIの呼出完了のみ。独立再読・fsyncされた`PERSISTED_VERIFIED`ではなく、なお`PERSISTENCE_CLAIM`相当である。部分書込・非原子的3stream CSV・poll欠損・確定可能時刻は依然UNKNOWN/NOT_CLOSED。
- PowerShell 5.1異常系の合成負例で関数のふるまいは試せるが、OWNER PCの実RSS/Excel負荷、W1–W4、終了/再起動・同期I/O停止を保証しない。休場中でも本番Collector起動は許可されていない。
- 取引所時刻、真のtick方向や全約定、分足の完全性はない。CSV parser Q1成功でもQ2真正性/Q3 PITは未合格。欠測nullラベルを新しい価格の信頼性認証にしてはならない。

## 合成Windowsテストの実装設計

`tests/ms2_collector_safe_append_fault.ps1` はWindowsPowerShell 5.1を要件とし、PowerShell Parser ASTから**実Collectorの安全append関数の定義だけ抽出**して実行する。Collectorスクリプト全体は**実行しない**ためExcel/COM・MS2・VOICEが起動しない。合成一時ファイルで成功、throw、部分書込後throw、`Write-Error -ErrorAction Stop`、無断再送なし、private exception/path非出力、実Collector AST構文と変更箇所、実注文禁止を検査する。Python静的試験はLinux/Windows双方でソースの9箇所、欠測元データの捕捉、fail-closed、過去CSV列不変を検証する。

## 未承認・次の独立ゲート

1. **実証すべき次P0**：非ブロッキングproducer/別Writer、bounded producer overhead、async writer STOP/KILL、cold startup・CPU負荷・保管回復、Q2/Q3 session/poll/available_at、プライベート再読、Windows PS5.1実プロセスfault injection。既存#379 Contract再利用、14本Draft依存を無条件追加しない。
2. 本番Collectorへの適用前にOWNERが別途明示承認。Windows端末からprivate原本をpublic GitHubやチャットへ送らない。
3. READMEやCIの合成PASSを本番readyにしない。実観測適格N=0、EV/PF/DD/純利益/100億残額UNKNOWN。`real_submit_allowed=false`, `promotion_eligible=false`, `statistical_edge_confirmed=false`。**DO NOT MERGE**。

## 次の検収

最新PR HEADのWindowsPowerShell5.1およびWindows/Linux Python静的回帰を確認し、失敗は原因を修正して再実行。実コードを改変した箇所・失敗再現内容・PR HEAD/CI/アクション未承認状態をIssue #376/PR/調整 #282へ記録。
