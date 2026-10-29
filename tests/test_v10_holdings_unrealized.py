"""OWNER 2026-10-27 「保有銘柄が現在含み損か含み益か一目で分かるようにして」: each virtual holding card shows
含み益 (green) / 含み損 (red) with the live price, computed from the fresh rows the screen already trusts; with no
fresh live price it says 現在値なし and shows no old number."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_screen_shares_only_fresh_rows_and_nothing_when_stale():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "window.cockpitLivePrices=stale?null:{at:Date.now(),rows:Object.fromEntries(" in html
    assert ".filter(x=>rowReady(x))" in html.split("window.cockpitLivePrices=", 1)[1].split("\n", 1)[0]


def test_cards_show_unrealized_pl_from_entry_or_reference_price():
    js = (ROOT / "trade_control.js").read_text(encoding="utf-8")
    assert "function unrealized(code,entry,isShort,lastOk)" in js   # lastOk: carried positions (OWNER 2026-10-27)
    assert "Date.now()-lp.at<=30000" in js                       # at most 30 s old
    assert "(isShort?1-now/e:now/e-1)*100" in js   # OWNER 2026-10-27: short = 1 - now / entry, as the scoring
    assert '"含み損益：現在値なし"' in js and '"含み益 "' in js and '"含み損 "' in js
    assert "plLine(unrealized(String(p.ticker||\"\").replace(/\\.T$/,\"\"),p.fill_price," in js
    assert "plLine(unrealized(String(p.ticker||\"\").replace(/\\.T$/,\"\"),p.reference_price,p.side!==\"LONG\",true))" in js


def test_pl_colours():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert ".cc-pl.pl-plus b{color:#35e2ae}" in html and ".cc-pl.pl-minus b{color:#ff5a5f}" in html


import unittest as _unittest  # noqa: E402


class FunctionTests(_unittest.TestCase):
    """The test_ functions above, run by `python -m unittest` (CI) as well."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(FunctionTests, _name, (lambda f: lambda self: f())(_fn))


class CarriedUnrealized(_unittest.TestCase):
    def test_carried_positions_use_the_last_price_after_the_close(self):
        # OWNER 2026-10-27 「持ち越し銘柄も含み益・損いれるように」
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("window.cockpitLastPrices={asof:String(d.updated_at||\"\").slice(11,16),rows:", html)
        self.assertIn('tag="（最後の値・"+(lq.asof||"時刻不明")+"）"', js)
        self.assertIn('.concat(on.map(p=>gHeld("仮想・持越",p,p.reference_price,p.side!=="LONG",true)));', js)
        self.assertIn('p.reference_price,p.side!=="LONG",true))));', js)

