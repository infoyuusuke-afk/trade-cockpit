"""NEXT discovery foundation, phase 1.

Japan-market exploration only. This package does not place orders and does
not read MarketSpeed II, RSS, or Excel.
"""

from scripts.next_foundation.pipeline import run

__all__ = ["run"]
