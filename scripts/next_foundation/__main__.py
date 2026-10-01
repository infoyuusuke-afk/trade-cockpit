"""Build a NEXT board from a universe snapshot file.

This entry point reads a local fixture or snapshot. It does not contact
TradingView, MarketSpeed II, RSS, or Excel.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.next_foundation.config import load_config
from scripts.next_foundation.pipeline import run, write_board


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the phase-1 NEXT board")
    parser.add_argument("--input", required=True, help="Universe snapshot JSON")
    parser.add_argument("--config", default=None, help="Score config JSON")
    parser.add_argument("--previous", default=None, help="Previous membership JSON")
    parser.add_argument("--out", required=True, help="Board JSON output path")
    parser.add_argument("--log", default=None, help="Judgment JSONL path")
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    config = load_config(args.config) if args.config else load_config()
    board = run(payload, config=config, previous=previous, log_path=args.log)
    write_board(args.out, board)
    print(
        f"next board symbols={board['universe_count']} active={board['active100_count']} "
        f"next20={len(board['next20'])} next5={len(board['next5'])} "
        f"fail_closed={board['fail_closed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
