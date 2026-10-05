"""Japanese subtitles: display-width wrap, kinsoku, unbreakable number+unit, per-language
caption tracks, per-language fonts (fail-closed) and English backward compatibility."""
import json
import textwrap
import unittest

from auto_publish.app.compliance.rules import check_captions_srt
from auto_publish.app.config import load_config
from auto_publish.app.errors import RenderError, ValidationError
from auto_publish.app.render.ffmpeg_render import FfmpegRenderer, build_srt, text_inputs, timeline
from auto_publish.app.text.wrap import NO_END, NO_START, TOKEN, display_width, units, wrap_display, wrap_text
from auto_publish.tests.helpers import GOLDEN_DIR


def _post(lang):
    return json.loads((GOLDEN_DIR / f"TEST1_{lang}.json").read_text(encoding="utf-8"))


def _all_ja_texts():
    out = []
    for sid in ("TEST1", "TEST3"):
        post = json.loads((GOLDEN_DIR / f"{sid}_ja-JP.json").read_text(encoding="utf-8"))
        out += [post["title"]] + [s["text"] for s in post["segments"]]
    return out


class TestDisplayWidth(unittest.TestCase):
    def test_widths(self):
        self.assertEqual(display_width("abc"), 3)
        self.assertEqual(display_width("終値"), 4)
        self.assertEqual(display_width("ｱｲ"), 2)              # half-width katakana
        self.assertEqual(display_width("（テスト）"), 10)       # full-width brackets
        self.assertEqual(display_width("2,345円"), 7)


class TestJapaneseWrap(unittest.TestCase):
    def test_golden_wrap_of_fixture_segments(self):
        segs = {s["id"]: wrap_display(s["text"], 32) for s in _post("ja-JP")["segments"]}
        self.assertEqual(segs["b1"], ["終値は2,345円、前日比+6.40%。"])
        self.assertEqual(segs["b2"], ["日本時間09:12、レーダーが出来高", "急増を検知。"])
        self.assertEqual(segs["b3"], ["ペーパートレード（シミュレーショ", "ン・実資金ではありません）：買い",
                                      "2,250円から、結果+1.19R。"])
        self.assertEqual(segs["hook"][0], "フィクスチャ・メモリーHD")   # （TEST1） kept together

    def test_properties_over_all_fixture_texts_and_widths(self):
        for text in _all_ja_texts():
            nums = [m.group(0) for m in TOKEN.finditer(text) if m.lastgroup == "num"]
            for width in range(8, 41):
                lines = wrap_display(text, width)
                self.assertEqual("".join(lines).replace(" ", ""), text.replace(" ", ""), (text, width))
                for i, line in enumerate(lines):
                    self.assertEqual(line, line.strip())
                    unit_count = len([u for u in units(line) if u != " "])
                    if unit_count > 1:
                        self.assertLessEqual(display_width(line), width, (line, width))
                    if i > 0:
                        self.assertNotIn(line[0], NO_START, (text, width, lines))
                    if i < len(lines) - 1:
                        self.assertNotIn(line[-1], NO_END, (text, width, lines))
                if width >= 10:   # every number+unit run fits a line => never split
                    for n in nums:
                        self.assertTrue(any(n in line for line in lines), (n, width, lines))

    def test_number_and_unit_never_split(self):
        lines = wrap_display("価格は2,345円で前日比+6.40%、結果は+1.19Rでした", 8)
        for n in ("2,345円", "+6.40%、", "+1.19R"):
            self.assertTrue(any(n in line for line in lines), (n, lines))

    def test_kinsoku_pushes_units_together(self):
        # 「。」 may not start a line: it travels with the preceding character
        self.assertEqual(wrap_display("あいうえ。", 8), ["あいう", "え。"])
        # 「（」 may not end a line: it travels with the following character
        self.assertEqual(wrap_display("あいう（え）", 8), ["あいう", "（え）"])
        # small kana / prolonged sound mark do not start a line
        self.assertEqual(wrap_display("あいうちょ", 8), ["あいう", "ちょ"])
        self.assertEqual(wrap_display("あいうデー", 8), ["あいう", "デー"])

    def test_overlong_single_unit_is_the_only_hard_split(self):
        self.assertEqual(wrap_display("ABCDEFGHIJ", 4), ["ABCD", "EFGH", "IJ"])

    def test_english_wrap_is_r1_textwrap(self):
        for seg in _post("en-US")["segments"]:
            for width in (24, 30, 34, 36, 42):
                expect = "\n".join(textwrap.wrap(seg["text"], width=width, break_long_words=True,
                                                 break_on_hyphens=False)) or " "
                self.assertEqual(wrap_text(seg["text"], width, "en-US"), expect)


class TestCaptionTracks(unittest.TestCase):
    def test_english_srt_unchanged(self):
        post = _post("en-US")
        tl = timeline(post, 6)
        self.assertEqual(build_srt(tl), build_srt(tl, "en-US"))
        self.assertIn("00:00:24,000 --> 00:00:30,000", build_srt(tl))

    def test_japanese_srt_uses_display_width(self):
        post = _post("ja-JP")
        srt = build_srt(timeline(post, 6), "ja-JP")
        for line in srt.splitlines():
            if line and not line[0].isdigit():
                self.assertLessEqual(display_width(line), 32, line)
        self.assertIn("終値は2,345円、前日比+6.40%。", srt)
        self.assertFalse(check_captions_srt(srt, "ja-JP"))
        self.assertEqual(check_captions_srt("", "ja-JP")[0]["lang"], "ja-JP")

    def test_japanese_burned_text_labels(self):
        post = _post("ja-JP")
        files = text_inputs(post, timeline(post, 6), "2026-09-24", "ja-JP")
        self.assertEqual(files["t_header.txt"], "東京市場 大引け  |  2026-09-24")
        self.assertTrue(files["t_b1.txt"].startswith("・終値"))
        self.assertIn("テスト用", files["t_fixture.txt"])
        en = text_inputs(_post("en-US"), timeline(_post("en-US"), 6), "2026-09-24")
        self.assertEqual(en["t_header.txt"], "JAPAN MARKET CLOSE  |  2026-09-24")
        self.assertTrue(en["t_b1.txt"].startswith("- It closed"))


class TestFontsFailClosed(unittest.TestCase):
    def test_missing_japanese_font_fails_closed(self):
        cfg = load_config(overrides={"render": {"fonts": {"ja-JP": ["/nonexistent/NoSuchFont.ttc"]}}})
        r = FfmpegRenderer(cfg)
        with self.assertRaises(RenderError) as cm:
            r._font("ja-JP")
        self.assertEqual(cm.exception.code, "FONT_MISSING")
        self.assertEqual(cm.exception.details["lang"], "ja-JP")

    def test_language_without_font_list_fails_closed(self):
        with self.assertRaises(RenderError) as cm:
            FfmpegRenderer(load_config())._font("ko-KR")
        self.assertEqual(cm.exception.code, "FONT_MISSING")

    def test_english_font_list_is_unchanged(self):
        r = FfmpegRenderer(load_config())
        self.assertEqual(r.font_candidates("en-US"), load_config()["render"]["font_candidates"])

    def test_windows_japanese_fonts_are_candidates(self):
        cands = FfmpegRenderer(load_config()).font_candidates("ja-JP")
        self.assertTrue(any("YuGoth" in c for c in cands) and any("meiryo" in c for c in cands))


class TestVariantConfig(unittest.TestCase):
    def test_default_is_english_only(self):
        self.assertEqual(load_config()["render"]["variants"], ["en_primary"])

    def test_invalid_variants_rejected(self):
        for v in ([], ["ja_primary"], ["en_primary", "en_primary"], ["en_primary", "fr_primary"]):
            with self.assertRaises(ValidationError, msg=v) as cm:
                load_config(overrides={"render": {"variants": v}})
            self.assertEqual(cm.exception.code, "RENDER_VARIANT_INVALID")


if __name__ == "__main__":
    unittest.main()
