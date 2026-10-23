# Issue #374 DATA-FIRST offline audit
基準main: 4b66ed01e5bfb878ec05166238791492828b218e。Watcher blob ae04c90572b6352a5e56d077f29b4029187c43a9。
最新指示: https://github.com/infoyuusuke-afk/trade-cockpit/issues/374#issuecomment-6171615220
#282本文・運用規約6155935345・最新コメント6171115320確認。原本は取得していない。

## 判定
A: GO（offline private legacy品質集計のみ）。実観測の存在・適格化はNOT VERIFIED。
B: NO_GO（今回の実観測開始の先行条件として）。廃棄ではなく後工程に保留。
Aは既存出力を読み取れる設計。OWNER PCの原本存在、稼働版SHA、出力期間・鮮度は未確認。
AのCSVで正確なtick復元・完全板・Fill Model・売買判断はNO_GO。
Read-only監査は保存側の新しい障害を価格・音声処理へ持ち込まない。ただし現Watcher自身の保存失敗隔離は保証されていない。

## 品質制約
|対象|コードで確認した事実|推定・欠損・重複・順序の制約|研究可能範囲|不可|
|---|---|---|---|---|
|ticks|Read-TickList CurrentRegionからdouble正値のみ。OADateはHH:mm:ssへ丸め、文字時刻はそのまま。Write-TickLogDiffのrecorded_atは同一pollローカル秒、volumeは表示数量、poll_seqは呼出番号|同一時刻価格数量は一つ。350キーで保持・末尾350行を再読、poll_seq再起動0。再起動前のpollと衝突。空読取はCOM失敗と無約定を区別不可。日付ファイル名は起動時固定で日跨ぎ混入。offset/available_at/約定IDなし。新しい順の可能性を含め表示配列順を追記、取引所順序不明|形式・非有限値・再出現キー・poll低下・記録時計逆行・期待日付違い・記録間隔の疑い|完全tick・真の出来高・秒内順序・PIT可用時刻・実約定/Fill|
|diag|poll_time,window_size,overlap_with_prev,new_appended,suspected_gap。gapは前poll非空かつ重複0かつ今poll非空|初回/再起動/空poll直後はgap=Falseでも欠損否定不可。重複ありでも部分欠損可。poll_seqなし、同秒衝突がありtickとの確定join不可。時計は秒・offsetなし|疑い発生頻度、空窓・zero overlap・件数矛盾・記録停止疑い|欠損数確定、全poll保存保証、gap=Falseによる完全性|
|quotes|日付・HH:mm、1分最初の成功時に追記。OVER/UNDERはB9/B10、best ask/bidはB7/B8|片方nullは0として保存。真0と欠測が不可逆。同分再起動は重複し得る。状態「約定あり」はprice存在から推定、実約定証明ではない。40逐次Value2の板10本はCSV保存されない|1分の気配代理指標による探索、欠損疑い・形式集計|atomic板10本・注文キュー・見せ玉識別・Fill/滑り・収益|
特記事項: Write-TickLogDiffはファイル追記前にキーをRAMに追加し、追記失敗なら同プロセスの再pollでも未保存キーが抑止され得る。diagはtick後の別追記でtransactionではない。
Write-TickLogDiffは外側loop try内の価格読取より前。I/O例外で当該pollの価格/シグナル/音声処理までskipし得る。既存Watcherが「保存故障で価格処理を止めない」要件を満たすとは主張しない。修正は禁止範囲なので未変更。
音声は同期Speak/Mutex待ち、COM retry、workbook Save、2秒Sleepが同ループにあり、2秒周期や5msの保証ではない。

## A/B比較
|項目|A|B|
|---|---|---|
|工程数|offline validator→CI→別承認の原本存在/停止状態確認→privateコピー監査（原本があれば新collector不要）|統合cut設計→冷間/5ms/認証/停止/PIT解決→CI→個別承認Watcher配線→実機→蓄積|
|Watcher干渉/COM|追加0、MS2/Excel接続0|現時点未接続。将来の配線・実機検証必須|
|起動停止|単発offlineのみ。既存Windows障害を修復しない|新Producer/Worker/IPC世代と停止・復旧管理必要|
|欠損検証|制約付きlegacy集計、完全性はUNKNOWN|receipt/readback/poll台帳あり、cold failure/UNKNOWN/same-user等未解決|
|private保護|入力明示・元CSV不変・値/行/パス/ハッシュを集計に出さない、外部送信なし|既存private JSONL境界と認証未解決、本番NO_GO|
|コスト/保守|新規小adapter、数値チェックはmain既存broker preflight再利用|14stack・main分岐・複数process保守|
|OWNER負担|市場外1回の既存ファイル検査と明示入力。実機承認別|新起動/停止/異常受入の複数操作|
|安全停止|監査のみexit2、異常入力BLOCKED、原本保存側に影響しない|STOP_PENDING/冷間gate/OS IO認証P0継続|
Aは過去ログ存在時に最短。存在しなければ今回作業だけでは新市場データは増えない。既存Watcherの継続稼働承認や安全性保証も含まない。

## 既存validator再利用
main scripts/private_broker_csv_preflight.py の _number とMAX_BYTESをimport。既存コード変更なし。
ms2_local_acceptance.pyはloopback接続用でCSV未対応、naive時計にnow.tzinfo補完するため今回使わない。
Resample_Kioxia_Ticks_15s.ps1は出力書込・品質gateなし、配列順OHLCなので正確な15秒足証拠に昇格不可。
Analyze_BoardBias_Today.ps1は中値代理探索・sort/無効行skipで品質gateではない。
#347契約audit_sidecar_bytesはLEGACY_CSV_NOT_MIGRATEDで拒否。これを変更せず、CSVをsidecarへ偽変換しない。実約定validatorも再実装しない。
最小adapterはCSVの品質countsだけ。timezone/freshnessは常にUNKNOWN、全3flagsfalse、N0。diag↔tickの確定joinはしない。
10秒/120秒の間隔チェックは探索上の疑いフラグで、SLA/5ms閾値ではない。
入力はUTF-8 BOM許容、MAX_BYTES、完全末尾行、header/行/非有限値/時計/poll/重複検証。ネットワークパス・リンク拒否、stat変化検知。敵対同一user/TOCTOU完全防御・Windows mapped drive/電源断は保証しない。明示ローカル停止済みコピーのみ。
正常に集計できてもLEGACY_ONLY_BLOCKED/exit2。これはツール失敗と品質適格PASSを混同させないため。CLI標準出力は集計のみ、自動送信・ファイル書込なし。

## 14 Draft / Release Cut
全14本OPEN Draft・未マージ。現在base SHAはGitHubが返した値で、歴史的起点SHAとは区別。
main vs #373はahead36/behind31/59 files。base直接切替・一括merge・history上書き不可。
|PR|head SHA|base ref/SHA|機能|分類|
|---|---|---|---|---|
|#347|ce2f43b66cbb138320da8813d90f59b8cb909da0|main / 1243ef1dd7001d36b789c4855e0626e8e896cce5|P0: offline private MS2 watcher sidecar contract|後工程・Aには不要|
|#349|0b41bc66ea4160e3382c75b5532c68d15dced57a|cursor/ms2-watcher-sidecar-ae03 / ce2f43b66cbb138320da8813d90f59b8cb909da0|P0: offline writer for captured MS2 board snapshots|後工程・Aには不要|
|#351|b7ed5ae7f2a1eaca7aa13290730b7058958f2ac5|cursor/ms2-offline-observation-writer-6f2b / 0b41bc66ea4160e3382c75b5532c68d15dced57a|P0: offline preflight for MS2 watcher sidecar isolation|後工程・Aには不要|
|#353|728b45367d0c925fa50d2b73331788eafb8a3e9e|cursor/ms2-watcher-integration-preflight-1cc7 / b7ed5ae7f2a1eaca7aa13290730b7058958f2ac5|P0: bounded non-blocking handoff for captured MS2 boards|後工程・Aには不要|
|#355|53ebc5c494ada8fffa4f5d89cdf8a4ea56ce1840|cursor/ms2-nonblocking-handoff-afcb / 728b45367d0c925fa50d2b73331788eafb8a3e9e|P0: offline PowerShell-to-Python slot for captured MS2 boards|後工程・Aには不要|
|#358|4910f11dd8bdc03782463b68dce447684dd505c3|cursor/ps-python-ipc-contract-1b7b / 53ebc5c494ada8fffa4f5d89cdf8a4ea56ce1840|P0: Windows-capable offline durable MS2 JSONL writer|後工程・Aには不要|
|#360|7ecb2d74790e032d787121b5d39773a47c1061bc|cursor/ms2-windows-durable-writer-77ea / 4910f11dd8bdc03782463b68dce447684dd505c3|P0: Windows spawned handoff to existing durable writer (Issue #359)|後工程・Aには不要|
|#361|48404f1d753cf6b5006f22e0e0cd6e81669f4806|work/issue359-windows-handoff / 7ecb2d74790e032d787121b5d39773a47c1061bc|P0: IPC slot integrity and crash fencing (Issue #356, offline only)|後工程・Aには不要|
|#363|ca3ccf54bf50294827a1b8218e7f1d92afadd5ea|work/issue356-ipc-integrity / 48404f1d753cf6b5006f22e0e0cd6e81669f4806|P0 #362: creation-time IPC ACL, owner-death fencing and Windows phase timing|後工程・Aには不要|
|#365|ff1fa0fa63684217a87c3b0ae7eefce3a2a4f7b9|work/issue362-ipc-security / ca3ccf54bf50294827a1b8218e7f1d92afadd5ea|P0 #364: offline commit fence, same-user refusal and Windows latency trace|後工程・Aには不要|
|#367|4a269d91ecd5290075fb92ec3035d7f65c7fa78c|work/issue364-ipc-boundaries / ff1fa0fa63684217a87c3b0ae7eefce3a2a4f7b9|P0 #366: offline low-priority observation isolation and DROP boundary|後工程・Aには不要|
|#369|34a4dc751d3d95defd4232fb8229c7887bab08eb|work/issue366-isolated-observation / 4a269d91ecd5290075fb92ec3035d7f65c7fa78c|P0 #368: native PS5.1 offline capture and supervised durable DROP evidence|後工程・Aには不要|
|#371|19acb7649835bdb21b37785248a6312313449e19|work/issue368-native-drop / 34a4dc751d3d95defd4232fb8229c7887bab08eb|P0 #370: offline poll persistence reconciliation and separate PS5.1 latency cohorts|後工程・Aには不要|
|#373|9861b9ed0acb375bbe137c5b485a670c3d1feffe|work/issue370-poll-reconciliation / 19acb7649835bdb21b37785248a6312313449e19|P0 #372: offline native concurrent receipt / durable Writer reconciliation|後工程・Aには不要|
依存は#347→#349→#351→#353→#355→#358→#360→#361→#363→#365→#367→#369→#371→#373。
Aの最小cut: 最新main＋このCSV adapter/tests/workflow/docのみ。14本のmerge必要数0。
Bの将来の機能cut（PR単位cherry-pickではない）:
- 契約/品質gate=#347、Windows耐久Writer=#349+#358、preflight=#351、handoff=#353+#355+#360。
- 完全性・owner/世代・ACL・commit fence=#361+#363+#365、隔離/#367、DROP/#369、台帳/#371がBの将来安全要件。
- #373は検証fixture/測定、runtime導入には不要、継承試験候補。
旧POSIX writerは#358で代替・統合可能。橋/隔離/DROP経路の重複は将来cutで一本化候補だが、今回は削除/書換えなし。
Bは未解決ゲートがあるのでrelease実施NO_GO。cold IPC_GATE_ABANDONED、5ms NOT_MET、same-user認証/TOCTOU/OS IO/W1-W4を継続。
各HEAD Actions取得済み。#347 Owner Gate skippedはPASSではない。#373 Windows/Linux synthetic jobs successを確認、実機証拠ではない。

## 別承認後のWindows read-only受入案（今回は実行禁止）
市場が閉まっている時間で、OWNERが既存手順によりWatcher停止済みと確認できる場合だけ。仕事用ExcelやMS2を新規起動しない。停止方法不明/ログ更新中なら中断、Excel強制終了しない。
この工程のためにWatcherを開始/改修しない。原本不存在ならMISSING/N0で終了。
1. 対象repoの監査済みDraft codeを別作業コピーへ取得（mainへの上書き/mergeなし）。Python3.12がない場合インストールせず中断。未検証配布zipを使用しない。
2. PowerShellへ一回コピー: Get-Command python -ErrorAction Stop
3. 既知候補だけ存在確認（再帰検索なし）:
Get-ChildItem -LiteralPath 'C:\AI_Cockpit_Current\trade-cockpit\ms2_live' -File | Where-Object { $_.Name -match '^kioxia_(ticks|tick_diag)_[0-9]{8}\.csv$|^気配値ログ\.csv$' } | Select-Object Name,Length,LastWriteTime
この候補場所は未確認。なければ別path推測/PC走査はせずMISSINGで終了。
4. 対象日と原本の所在が確認できたら、停止済み3原本をrepo外D:\AI_Cockpit_Private\Issue374\へ一回手動コピー。OneDrive/共有driveを避ける。コピー前後の原本SHA256をPC内で比較、違えば中断。ハッシュ/原本/名前/時刻もGitHubへ送らない。
5. 監査codeの作業コピーをカレントとし、例（2026-10-14は明示対象日。勝手に今日へ変更しない）:
python -m scripts.ms2_legacy_csv_audit --kind ticks --date 2026-10-14 --input 'D:\AI_Cockpit_Private\Issue374\kioxia_ticks_20261014.csv'
python -m scripts.ms2_legacy_csv_audit --kind diag --date 2026-10-14 --input 'D:\AI_Cockpit_Private\Issue374\kioxia_tick_diag_20261014.csv'
python -m scripts.ms2_legacy_csv_audit --kind quotes --date 2026-10-14 --input 'D:\AI_Cockpit_Private\Issue374\気配値ログ.csv'
各コマンドを一つずつコピー。quotesは累積日付CSVなのでDATE_MISMATCHは対象日外を含むフラグで、行は削除しない。
全てexit2は意図したfail-closed。復旧は監査processをCtrl+C、入力修正なし。CSVやログは削除しない。受入が終わってもWatcher再起動はこの手順に含めない。
6. 原本不変・3reports・稼働版Watcher SHA・時計/日付の別証拠をPC内で照合。外部共有はOWNERが確認した匿名counts/理由のみ。N0維持。
正式実機実行は別途OWNER承認。価格/音声が正しく継続する受入は本手順の範囲外。
## 次の担当
Work: 本Draft合成Win/Linux CIと証拠を保存。通常GPT: 独立検収・上記受入の承認対象/配布形態を確定。
OWNER: 別承認後だけoffline private原本存在確認。現時点操作不要。
未達: 原本存在/稼働版一致/実品質/時計/欠損/市場外停止状態、実観測適格化基準。新IPC必要性はこの結果の後で判定。
実観測適格N0、EV/PF/DD/累積実現純利益/100億残額UNKNOWN。利益計上0。
この指示の完了はオフライン監査と許可された最小検証のみ。V10/Watcher修正・Windows実機接続・本番接続・mainマージ・実注文を承認しない。

