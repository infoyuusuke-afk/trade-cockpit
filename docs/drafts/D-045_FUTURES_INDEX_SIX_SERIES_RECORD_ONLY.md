# D-045 | 六系列先物・指数のPC非公開「記録専用」拡張（Draft 2026-10-22）

決定: OWNER指示により D-044 研究の未観測データを補う独立・非公開データ収集候補を隔離実装する。実行中V10への統合と取引利用は未承認。D-035本番修正、D-019権利確認、OWNERの正確なSHA承認が済むまで有効化しない。docs/DECISIONS.mdの正本編集権限はPR #443の文書責任者に留保し、本ファイルを正本更新済みとは称さない。

## 対象：6系列

| ID | 商品 | 使用する関数とコード |
| --- | --- | --- |
| N225_MINI_F | 日経225ミニ先物 中心限月 | RssFOPCode("N225MF","YYYYMM") で9桁を解決、RssFOPMarket |
| TOPIX_F | TOPIX先物 中心限月 | RssFOPCode("TOPXF","YYYYMM") で9桁を解決、RssFOPMarket |
| GROWTH250_F | 東証グロース市場250指数先物 中心限月 | RssFOPCode("MOTF","YYYYMM") で9桁を解決、RssFOPMarket |
| N225_I | 日経225指数 | RssIndexMarket("N225",項目) |
| TOPIX_I | TOPIX指数 | RssIndexMarket("TOPX",項目) |
| GROWTH250_I | 東証グロース市場250指数 | RssIndexMarket("MTHR",項目) |

確認資料: https://marketspeed.jp/ms2_rss/onlinehelp/ohm_002/ohm_002_03.html / https://marketspeed.jp/ms2_rss/onlinehelp/ohm_002/ohm_002_07.html / https://marketspeed.jp/guide/manual/ms2rss_function.pdf

中心限月は「期近」と機械的に同一視しない。3つの限月YYYYMMをそれぞれOWNERのMS2画面で確認し手入力。中心限月の自動切替は今回対象外。MOTFとMTHRは旧マザーズと表記される古いマニュアルがあるが現行の公式オンラインヘルプに掲載されたコードを採用し、PCで検証する。

## 収録項目

先物: RssFOPMarketの現在日付、現在値、現在値詳細時刻(HH:MM:SS)、出来高、出来高加重平均(VWAP相当)、最良買/売気配値1、最良買/売気配数量1。指数: RssIndexMarketの現在日付、現在値、更新時刻(HH:MM)、出来高。指数にないVWAPや秒単位詳細時刻は記録しない。取得不可はNULL扱い、0・推定値を補完しない。

受信JST(ISO8601)、元データの日付・時刻・粒度、コード・限月を独立項目として保持する。両者の時刻は独立に検証する。秒粒度を持たない指数を秒単位の先物先導と結論しない。real_time_verified=UNVERIFIED。リアルタイム性・取得項目の動作はWindows実機未確認。

## 周期・保存・隔離

10秒周期（10～60秒の範囲のみ設定可）。6系列を1回のExcel COM矩形読み出しで観測。変化のないレコードは重複保存しない。私有リポジトリ外の指定済みOWNER PCローカルフォルダにJST観測日別 CSVをappend-only記録し、書込みは排他ロック+fsync。再起動重複・外部リンク・不正型・未来/古い時刻・不明なコード/限月をfail-closed。夜間の観測日とソース取引日を混同しない。100銘柄RSS、LIVE判断、鮮度、売買、音声、UI配色、Shadowは現状のまま維持。新規定時実行・自動起動・API課金・GitHubへの実数転載をしない。

## ステージ別許可

- Probe【今夜条件付き許可】: V10を安全停止・残留無し、Excel 1プロセス/1冊にして新しい未保存の一時ブックを開く。PCで各中心限月を確認してからPowerShellの Probe モードで6行の式を追加。実数・ラグを画面確認するだけ。Excel自動保存/自動終了なし。OWNERが一時ブックを**保存せずに閉じる**。現行V10ブックに触れずCSVも書かない。
- Install【別OWNER承認待ち】: D-035受入、D-019利用権利、対象SHA承認後にのみ1つの既存V10ブック内へD045_FUTURES_INDEXシートを追加する。元100銘柄/JNX/IRシートは変更しない。コードはブックを自動保存しない。
- Once/Run【別OWNER承認待ち】: セットアップ後、明示的な権利確認/D035受入/OWNER承認フラグとPC内の非公開保存先が揃ったときだけ起動。Runは手動かつ単一プロセス、デフォルト1回。既存Controllerに自動登録しない。
- 正式接続前に既存100銘柄の欠損率、Excel COMエラー、Collector実測遅延（通常/負荷）を比較し、劣化時は本モジュールだけ停止。新データをD-044分類器やBrain実判断に使うには別の正本仕様/検証/OWNER承認が必要。

## D-019データ権利

既存D-019はMS2 RSSを機械処理データの主候補としているが、先物・指数のCSV長期蓄積、AI分析、再配布を含む用途の個別許可は未確認。公式関数マニュアルの存在は二次利用権限の証明ではない。今回のProbeは本人のPC内・未保存での適合性確認に限る。継続保存・契約範囲外への処理/共有は禁止し、関連の最新契約文言が確認できた場合に別ゲートで解放する。GitHub、SNS、外部API、クラウドには先物の実数値を送らない。

## Acceptance

T01 六系列と正しいRssFOPCode/RssIndexMarket（MOTF/MTHRを含む）を検証。
T02 秒/分のソース粒度を保持、取得不能・未来時刻・古い時刻・エラーを拒否。
T03 限月失効・未確定コードを拒否し、限月ロールを暗黙に行わない。
T04 private CSVのみ、重複排除、単一writer、Symlink拒否、再起動保全。
T05 Windows PowerShell構文とLinux/Windows合成CI PASS。
T06 Excel1冊/1プロセス、V10停止中一時ブックProbeの公式値取得確認。
T07 D-035切替後の実機負荷・鮮度・保存検収。
T08 D-019の文書証拠・独立監査・OWNER対象SHA承認後のみ本番実行。
T09 real_submit_allowed=false、取引経路を変更しない。

STATUS: Draft IMPLEMENTED候補。CI/Windows実機/権利/本番Acceptanceは別個に判定。収益・実P/L・費用・100億円残額UNKNOWN。
