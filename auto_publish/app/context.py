from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .clock import Clock
from .config import Paths


@dataclass
class Ctx:
    conn: sqlite3.Connection
    clock: Clock
    cfg: dict
    paths: Paths
    actor: str = "system"
