#!/usr/bin/env python3
import json,tempfile,unittest
from pathlib import Path
from scripts.strategy_registry import load_keys,validate

class StrategyRegistryTests(unittest.TestCase):
    def test_known_key(self):
        self.assertTrue(validate("OR15_BREAKOUT_LONG"))
    def test_unknown_fails_closed(self):
        self.assertFalse(validate("OR15_LONG_GUESS"))
    def test_duplicate_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"r.json";p.write_text(json.dumps({"strategies":[{"strategy_key":"X"},{"strategy_key":"X"}]}))
            with self.assertRaises(ValueError): load_keys(p)
if __name__=="__main__": unittest.main()
