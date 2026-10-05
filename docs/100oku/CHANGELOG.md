# CHANGELOG

`D:\100億PROJECT\MASTER_SPEC` は未反映。このファイルはリポジトリ側の差分である。Cloud Agent は D: へ書いていない。

## 2026-10-06

- `9180eb9ec`: Research Data Lane の `short_sale_ratio` を初の `FETCHED` にした。JPX空売り売買代金合計を raw / history / latest に保存し、Research Layer から参照する。`trading_adoption=false`。LIVE signal は変えていない。
- freshness を「4暦日以内」だけに依存させず、JPX休業日表の営業日差を併用した。長期休業をまたぐ最新公表が、暦日数だけで `STALE` にならない。
- 時刻を `session_date` / `first_seen_at` / `published_at` に分けた。`published_at` は検証できた HTTP `Last-Modified` だけを入れる。空売り比率の 2026-10-05 は `published_at=2026-10-05T16:30:28+09:00`、`first_seen_at=2026-10-06T01:13:15.683407+09:00`。
- `investor_futures_flow` を2本目の `FETCHED` にした。2026-09-24〜09-25 の海外投資家・日経225先物売買代金差引は 186,407,123,040 円。`published_at=2026-10-01T15:30:29+09:00`。Research Data Lane は FETCHED 2/17。
- Owner PC 同期ブリッジを追加した。`downloads/SYNC_100OKU_MASTER_SPEC.ps1` が `docs/100oku/` を `D:\100億PROJECT\MASTER_SPEC` へコピーし、上書き前を `archive\YYYY-MM-DD_HHMM\` に退避する。sha256 の不一致、欠落、空ファイルは FAIL CLOSED。`LAST_SYNC.json` の `cloud_agent_wrote_destination` は false。`downloads/REGISTER_100OKU_MASTER_SPEC_TASK.ps1` は毎日 16:45 を表示し、`-Register` が無いときは登録しない。Cloud 上の dry-run は D: へ書いていない。
