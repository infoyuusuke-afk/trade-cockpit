"""Temporary probe: run the fixed parser on the real JPX workbooks.

Prints only which subjects parsed, the net sign and the regime name; no JPX
figures reach the public log. Delete this file and its workflow before merge.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts import investor_regime as ir

out = ir.build_output(datetime.now(ZoneInfo("Asia/Tokyo")))
manifest = ir._load_manifest()
new = [r for r in manifest if "stock_1_w_" in r.get("source_url", "")]
print("new weekly files archived:", [(r["period_start"], r["period_end"]) for r in new])
for r in new:
    parsed = ir.parse_equity_workbook(ir.ROOT / r["local_file"], r["period_end"], r["period_start"])
    if not parsed:
        print(r["period_end"], "PARSE FAILED")
        continue
    signs = {k: ("買越" if v["net"] > 0 else "売越") for k, v in parsed["subjects"].items()}
    share = parsed["subjects"]["foreign"]["gross"] / parsed["market_turnover"] * 100
    print(r["period_end"], signs, "foreign share band:", "50-70%" if 50 <= share <= 70 else "OUTSIDE 50-70%")
print("asof:", out["asof"]["period_end"], "observed_weeks:", out["connection"]["observed_weeks"],
      "regime:", out["regime"]["name"])
