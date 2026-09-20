#!/usr/bin/env python3
import json
from pathlib import Path

REGISTRY=Path("data/strategy_registry.json")

def load_keys(path=REGISTRY):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    keys=[x["strategy_key"] for x in data["strategies"]]
    if len(keys)!=len(set(keys)): raise ValueError("duplicate strategy_key")
    return set(keys)

def validate(key, keys=None):
    if not key: return False
    return key in (keys if keys is not None else load_keys())
