"""Cockpit surface inventory. Statuses come from the current code, not a plan.

DONE means the named gate exists and has an Owner-verified or tested result.
PARTIAL means code is on a page or in a module and the lane is not finished.
NOT DONE means there is no implementation to classify as partial.
BLOCKED means the lane cannot proceed without a feed this repository does not have.
"""
from __future__ import annotations

SURFACES = (
    {
        "id": "control",
        "label": "Control",
        "status": "PARTIAL",
        "evidence": "trade_control.js draws the CONTROL tab and execution state. Broker positions stay disconnected unless a feed says connected. RssOrder is unimplemented.",
    },
    {
        "id": "scalp5",
        "label": "SCALP 5",
        "status": "PARTIAL",
        "evidence": "index.html has the SCALP 5 strip for five fixed names. docs/CARD_SYSTEM_CONTRACT.md says that strip is not on the shared card system yet. The tab does not add an order.",
    },
    {
        "id": "event5",
        "label": "EVENT 5",
        "status": "PARTIAL",
        "evidence": "The EVENT 5 tab exists. A full-market realtime scanner is not in the collector signal. Theme and earnings tables are still separate batches.",
    },
    {
        "id": "realtime5",
        "label": "REALTIME 5",
        "status": "PARTIAL",
        "evidence": "The ms2-live tab reads the collector board. Fail-closed price agreement is a separate gate. Screenless expectancy ranking is not the live signal.",
    },
    {
        "id": "kioxia",
        "label": "キオクシア",
        "status": "PARTIAL",
        "evidence": "The KIOXIA tab and 285A.T collector path exist. Time-of-day statistics and the forecast chart are not the intraday entry rule.",
    },
    {
        "id": "earnings",
        "label": "決算",
        "status": "PARTIAL",
        "evidence": "scripts/earnings_calendar.py, earnings-calendar.js, and the earnings workflow exist. The calendar does not set the live entry signal.",
    },
    {
        "id": "weekly_review",
        "label": "週間振返り",
        "status": "PARTIAL",
        "evidence": "index.html weekly-review keeps the 2026-09-19 counts. The pane labels that snapshot, shows theme names instead of a Python list, and does not copy those rows into the shadow ledger.",
    },
    {
        "id": "positions",
        "label": "保有ポジション",
        "status": "BLOCKED",
        "evidence": "The control pane shows broker positions as disconnected. Position RSS and RssOrder are unimplemented. Private holdings are not written to this repo.",
    },
    {
        "id": "commentary",
        "label": "実況",
        "status": "PARTIAL",
        "evidence": "On-air and radar placeholders wait for the Windows collector. They do not speak by themselves and they do not submit.",
    },
    {
        "id": "voice",
        "label": "音声",
        "status": "PARTIAL",
        "evidence": "voice_client.js talks to 127.0.0.1:28583 and the SBV2 bridge scripts exist. Playback needs that bridge on the Owner PC.",
    },
    {
        "id": "volume_surge",
        "label": "出来高急増",
        "status": "PARTIAL",
        "evidence": "The collector uses a volume burst in the fixed rule. Yahoo and TradingView ranking scripts are separate reference lists, not the live signal.",
    },
    {
        "id": "forecast_chart",
        "label": "予測チャート",
        "status": "PARTIAL",
        "evidence": "The Kioxia chart can draw a similar-day path. live_focus marks a date mismatch as unusable for trading. Missing one-minute bars stay unlabeled as actual prints.",
    },
    {
        "id": "price_consistency",
        "label": "現在値整合性",
        "status": "DONE",
        "evidence": "Collector, Gateway, and Strategy reject a stale, wrong-symbol, or wrong-workbook price. The Owner recorded the 285A.T agreement PASS. This does not cover the forecast chart.",
    },
    {
        "id": "mojibake",
        "label": "文字化け",
        "status": "PARTIAL",
        "evidence": "TDnet titles are decoded as UTF-8 in the collector. The weekly theme line no longer shows a Python list. PowerShell 5.1 can still misread a Japanese comment in a script that is not saved as ASCII.",
    },
    {
        "id": "trade_diary",
        "label": "AIトレード日記",
        "status": "PARTIAL",
        "evidence": "scripts/journal_projection.py maps an event into a row and projects a shadow trade without turning FEE_UNKNOWN into yen. The weekly pane says those rows are separate from the 2026-09-19 snapshot. It does not publish a diary, does not read private holdings, and does not submit.",
    },
)

_ALLOWED = frozenset({"DONE", "PARTIAL", "NOT DONE", "BLOCKED"})


def inventory() -> tuple:
    if len(SURFACES) != 15:
        raise RuntimeError("surface count drifted")
    seen = set()
    for item in SURFACES:
        if item["status"] not in _ALLOWED or item["id"] in seen or not item["evidence"]:
            raise RuntimeError("bad surface")
        seen.add(item["id"])
    return SURFACES
