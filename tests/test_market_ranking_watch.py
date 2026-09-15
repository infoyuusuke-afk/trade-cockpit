import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('mrw', Path(__file__).parents[1] / 'scripts/market_ranking_watch.py')
mrw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mrw)


SAMPLE_HTML = """
<html><body><table>
<tr><th class="RankingTable__head__2gX2">順位</th></tr>
<tr class="RankingTable__row__2x8_">
  <th scope="row" class="RankingTable__head__2gX2 RankingTable__rank__3dXJ">1</th>
  <td class="RankingTable__detail__16ZL">
    <a href="https://finance.yahoo.co.jp/quote/4933.T">(株)Ｉ－ｎｅ</a>
    <ul class="RankingTable__supplements__8-Ek">
      <li class="RankingTable__supplement__2s-i">4933</li>
      <li class="RankingTable__supplement__2s-i">東証PRM</li>
      <li class="RankingTable__supplement__2s-i"><a href="#">掲示板</a></li>
    </ul>
  </td>
  <td class="RankingTable__detail__16ZL RankingTable__detail--value__3mRC">
    <span class="StyledNumber__value__zj25">1,681</span>
  </td>
  <td class="RankingTable__detail__16ZL RankingTable__detail--value__3mRC">
    <span class="StyledNumber__value__zj25">+237</span>
    <span class="StyledNumber__value__zj25">+16.41</span><span class="StyledNumber__suffix__2KxK">%</span>
  </td>
  <td class="RankingTable__detail__16ZL RankingTable__detail--value__3mRC">
    <span class="StyledNumber__value__zj25">143,100</span><span class="StyledNumber__suffix__2KxK">株</span>
  </td>
</tr>
<tr class="RankingTable__row__2x8_">
  <th scope="row" class="RankingTable__head__2gX2 RankingTable__rank__3dXJ">2</th>
  <td class="RankingTable__detail__16ZL">
    <a href="https://finance.yahoo.co.jp/quote/8848.T">(株)レオパレス２１</a>
    <ul class="RankingTable__supplements__8-Ek">
      <li class="RankingTable__supplement__2s-i">8848</li>
      <li class="RankingTable__supplement__2s-i">東証PRM</li>
    </ul>
  </td>
  <td class="RankingTable__detail__16ZL RankingTable__detail--value__3mRC">
    <span class="StyledNumber__value__zj25">791</span>
  </td>
  <td class="RankingTable__detail__16ZL RankingTable__detail--value__3mRC">
    <span class="StyledNumber__value__zj25">+100</span>
    <span class="StyledNumber__value__zj25">+14.47</span><span class="StyledNumber__suffix__2KxK">%</span>
  </td>
  <td class="RankingTable__detail__16ZL RankingTable__detail--value__3mRC">
    <span class="StyledNumber__value__zj25">506,000</span><span class="StyledNumber__suffix__2KxK">株</span>
  </td>
</tr>
</table></body></html>
"""

EMPTY_HTML = "<html><body><p>no table here</p></body></html>"


class RankingsConfigTests(unittest.TestCase):
    def test_includes_both_up_and_down_for_stop_high_and_stop_low(self):
        keys = [key for key, _, _ in mrw.RANKINGS]
        self.assertIn("up", keys)
        self.assertIn("down", keys)


class ParseRankingHtmlTests(unittest.TestCase):
    def test_parses_two_rows_in_order(self):
        rows = mrw.parse_ranking_html(SAMPLE_HTML)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[1]["rank"], 2)

    def test_extracts_code_from_quote_link(self):
        rows = mrw.parse_ranking_html(SAMPLE_HTML)
        self.assertEqual(rows[0]["code"], "4933")
        self.assertEqual(rows[1]["code"], "8848")

    def test_extracts_name_market_price_change_volume(self):
        row = mrw.parse_ranking_html(SAMPLE_HTML)[0]
        self.assertEqual(row["name"], "(株)Ｉ－ｎｅ")
        self.assertEqual(row["market"], "東証PRM")
        self.assertEqual(row["price"], "1,681")
        self.assertEqual(row["change_yen"], "+237")
        self.assertEqual(row["change_pct"], "+16.41")
        self.assertEqual(row["volume"], "143,100")

    def test_missing_table_returns_empty_list_not_error(self):
        self.assertEqual(mrw.parse_ranking_html(EMPTY_HTML), [])

    def test_row_without_quote_link_is_skipped_not_guessed(self):
        html = """<html><body><table>
        <tr class="RankingTable__row__2x8_">
          <th class="RankingTable__rank__3dXJ">1</th>
          <td class="RankingTable__detail__16ZL">no link here</td>
          <td class="RankingTable__detail__16ZL"><span class="StyledNumber__value__zj25">100</span></td>
          <td class="RankingTable__detail__16ZL"><span class="StyledNumber__value__zj25">+1</span></td>
          <td class="RankingTable__detail__16ZL"><span class="StyledNumber__value__zj25">1</span></td>
        </tr></table></body></html>"""
        self.assertEqual(mrw.parse_ranking_html(html), [])


class AnnotateWatchedTests(unittest.TestCase):
    def test_marks_watched_and_unwatched_codes(self):
        rows = [{"code": "4933"}, {"code": "9999"}]
        annotated = mrw.annotate_watched(rows, {"4933"})
        self.assertTrue(annotated[0]["already_watched"])
        self.assertFalse(annotated[1]["already_watched"])

    def test_does_not_mutate_input_dicts(self):
        rows = [{"code": "4933"}]
        mrw.annotate_watched(rows, {"4933"})
        self.assertNotIn("already_watched", rows[0])


class LoadWatchedCodesTests(unittest.TestCase):
    def test_extracts_codes_from_ticker_field(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "watchlist.json"
            path.write_text(json.dumps({
                "stocks": {
                    "東京エレクトロン（8035）": {"ticker": "8035.T"},
                    "キオクシアHD（285A）": {"ticker": "285A.T"},
                }
            }), encoding="utf-8")
            codes = mrw.load_watched_codes(path)
        self.assertEqual(codes, {"8035", "285A"})

    def test_missing_file_returns_empty_set_not_error(self):
        codes = mrw.load_watched_codes(Path("/nonexistent/watchlist.json"))
        self.assertEqual(codes, set())


if __name__ == "__main__":
    unittest.main()
