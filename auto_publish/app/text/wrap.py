"""Display-width line wrapping for burned-in text and subtitles.

English keeps the R1 behaviour (``textwrap`` by character count) so existing
outputs are byte-identical. Japanese (and any other CJK text) is wrapped by
*display width* -- East Asian Wide/Fullwidth/Ambiguous = 2 cells, others = 1 --
with Japanese line-breaking rules (kinsoku):

* characters that may not start a line (。、）」 ... small kana, prolonged sound
  mark) are glued to the unit before them;
* characters that may not end a line (（「『【 ...) are glued to the unit after;
* a number with its sign/currency/unit (``2,345円``, ``+6.40%``, ``+1.19R``,
  ``09:12``) and a Latin word (``TEST1``) are single unbreakable units.

A unit wider than the whole line is the only thing ever split mid-unit (it
cannot fit anywhere); the result is fully deterministic.
"""
from __future__ import annotations

import re
import textwrap
import unicodedata

# may not begin a line
NO_START = frozenset(
    "、。，．・：；？！゛゜ー―‐〜～…‥々ゝゞヽヾ"
    "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶㇰㇱㇲㇳㇴㇵㇶㇷㇸㇹㇺㇻㇼㇽㇾㇿ"
    "）］｝〕〉》」』】〙〗〟’”)]},.:;!?%％"
)
# may not end a line
NO_END = frozenset("（［｛〔〈《「『【〘〖〝‘“([{¥$＄￥")

_UNITS = "%|％|円|銭|R|倍|株|年|月|日|時|分|秒|bp|pt"
TOKEN = re.compile(
    r"(?P<num>[+\-−±]?[¥$￥]?\d[\d,]*(?:\.\d+)?(?::\d{2})?(?:" + _UNITS + r")?)"
    r"|(?P<latin>[A-Za-z][A-Za-z0-9&'.\-]*)"
    r"|(?P<space>\s+)"
    r"|(?P<other>.)",
    re.S,
)


def char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1


def display_width(text: str) -> int:
    return sum(char_width(c) for c in text)


def units(text: str) -> list[str]:
    """Unbreakable units with kinsoku glue applied. Whitespace units are ' '."""
    out: list[str] = []
    for m in TOKEN.finditer(text):
        tok = m.group(0)
        if m.lastgroup == "space":
            if out and out[-1] != " ":
                out.append(" ")
            continue
        prev = out[-1] if out else None
        if prev is not None and prev != " " and (tok[0] in NO_START or prev[-1] in NO_END):
            out[-1] = prev + tok
        else:
            out.append(tok)
    while out and out[-1] == " ":
        out.pop()
    return out


def _hard_split(unit: str, width: int) -> list[str]:
    """Split a unit wider than the line; the break point is moved earlier when needed so
    a piece never starts with a NO_START char nor ends with a NO_END char."""
    parts, rest = [], unit
    while display_width(rest) > width:
        k, w = 0, 0
        while k < len(rest) and w + char_width(rest[k]) <= width:
            w += char_width(rest[k])
            k += 1
        k = max(k, 1)
        j = k
        while j > 1 and (rest[j] in NO_START or rest[j - 1] in NO_END):
            j -= 1
        if not (rest[j] in NO_START or rest[j - 1] in NO_END):
            k = j
        parts.append(rest[:k])
        rest = rest[k:]
    parts.append(rest)
    return parts


def wrap_display(text: str, width: int) -> list[str]:
    """Greedy display-width wrap honouring kinsoku and unbreakable number+unit runs."""
    lines: list[str] = []
    cur, curw, space = "", 0, False
    for u in units(text):
        if u == " ":
            space = bool(cur)
            continue
        w = display_width(u)
        sep = 1 if space and cur else 0
        space = False
        if cur and curw + sep + w > width:
            lines.append(cur)
            cur, curw, sep = "", 0, 0
        if not cur and w > width:
            pieces = _hard_split(u, width)
            lines.extend(pieces[:-1])
            cur, curw = pieces[-1], display_width(pieces[-1])
            continue
        cur += (" " if sep else "") + u
        curw += sep + w
    if cur:
        lines.append(cur)
    return lines


def is_cjk_lang(lang: str) -> bool:
    return lang.split("-")[0] in ("ja", "zh", "ko")


def wrap_text(text: str, width: int, lang: str = "en-US") -> str:
    """``width`` is characters for Latin languages (R1 behaviour) and display
    cells for CJK languages (full-width character = 2 cells)."""
    if is_cjk_lang(lang):
        return "\n".join(wrap_display(text, width)) or " "
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False)) or " "
