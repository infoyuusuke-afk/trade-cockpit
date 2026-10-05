# CURRENT_STATUS

記録日: 2026-10-06 JST

`D:\100億PROJECT\MASTER_SPEC` は未反映。この環境にそのパスは無く、書き込んでいない。ここにある3ファイルが、正式管理ファイルへ未適用の差分である。

## Research Data Lane

- FETCHED **2/17**
- `short_sale_ratio`: `9180eb9ec` で初の FETCHED。JPX空売り売買代金の市場合計。日次。`source_stage=OFFICIAL_PUBLIC`。`trading_adoption=false`。LIVE signal には接続していない。
- `investor_futures_flow`: 2本目の FETCHED。JPX投資部門別の先物週次CSV。海外投資家の日経225先物・mini・マイクロ売買代金差引。`trading_adoption=false`。LIVE signal には接続していない。
- 残り15件は `NOT_FETCHED`。
- `BASELINE_N=0`。`FEATURE_DELTA_EV=NOT_AVAILABLE`。`PROMOTION_CANDIDATE=NONE`。
- `real_submit_allowed=false`。

## 時刻と freshness

- `session_date` は対象セッションまたは週の最終日。
- `first_seen_at` はファイルを最初に観測した時刻。`available_at` はこれと同じ。
- `published_at` は HTTP `Last-Modified` がセッション日以降かつ初回観測以前のときだけ入る。無い場合は null。15:30 の掲載規則で過去時刻を埋めない。
- freshness は4暦日固定ではない。JPX休業日表の営業日差を使う。日次は直前営業日までを `FRESH` とする。週次は次週の第4営業日の前日までを `FRESH` とする。休業日表に無い年は `CALENDAR_MISSING` で研究値を出さない。
