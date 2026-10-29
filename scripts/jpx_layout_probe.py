"""Temporary probe: print the layout of the newest JPX investor-type workbook.

Numbers are masked (printed as N) so no JPX figures reach the public log.
Delete this file and its workflow once investor_regime.py is fixed.
"""
import io
import re
import sys
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import pandas as pd

PAGE = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html"


def fetch(url):
    return urlopen(Request(url, headers={"User-Agent": "TradeCockpit-JPX-PointInTime/1.0"}), timeout=30).read()


def mask(v):
    if pd.isna(v):
        return ""
    s = str(v).strip()
    if re.fullmatch(r"[-+]?[\d,]+(\.\d+)?", s):
        return "N"
    return s[:24]


html = fetch(PAGE).decode("utf-8", "replace")
links = [urljoin(PAGE, x) for x in re.findall(r'href=["\']([^"\']+\.xlsx?)["\']', html, re.I)]
print("xls links:", [l.rsplit("/", 1)[-1] for l in links])
target = next(l for l in links if "stock_1_w_" in l and "YYYY" not in l)
print("probe:", target.rsplit("/", 1)[-1])
sheets = pd.read_excel(io.BytesIO(fetch(target)), sheet_name=None, header=None)
for name, frame in sheets.items():
    print(f"\n=== sheet {name!r} shape={frame.shape}")
    for i in range(min(len(frame), 70)):
        cells = [f"{chr(65 + j) if j < 26 else j}:{mask(v)}" for j, v in enumerate(frame.iloc[i].tolist()) if mask(v)]
        if cells:
            print(f"r{i:02d} " + " | ".join(cells))
sys.stdout.flush()
