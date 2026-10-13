"""Fail-closed contracts for the display-only local Excel Watcher mirror."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def watcher_script() -> str:
    source = (ROOT / "scripts" / "update.py").read_text(encoding="utf-8")
    start_marker = 'ms2_live_script = r"""'
    start = source.index(start_marker) + len(start_marker)
    end = source.index('\n"""', start)
    return source[start:end]


class WatcherStaleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = watcher_script()
        cls.dashboard = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_built_dashboard_uses_same_fail_closed_script_as_generator(self):
        # Prevent a safe generator from coexisting with an unsafe deployed HTML.
        self.assertIn(self.script, self.dashboard)

    def test_every_displayed_watcher_signal_is_cleared_when_stale(self):
        match = re.search(
            r"const clearWatcherKioxia=\(status,source\)=>\{.*?const cleared=\{(.*?)\};",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Watcher stale reset helper missing")
        fields = set(re.findall(r'"(kio-watcher-[\w-]+)"\s*:', match.group(1)))
        self.assertGreaterEqual(
            fields,
            {
                "kio-watcher-source",
                "kio-watcher-signal",
                "kio-watcher-conditions",
                "kio-watcher-entry",
                "kio-watcher-target",
                "kio-watcher-under",
                "kio-watcher-flow",
                "kio-watcher-tick",
                "kio-watcher-board",
                "kio-watcher-bias",
                "kio-watcher-stopzone",
                "kio-watcher-pts",
            },
        )
        self.assertIn('Object.entries(cleared).forEach(([id,value])=>put(id,value))', self.script)

    def test_expired_missing_and_future_clock_values_fail_closed(self):
        self.assertIn("stale=age>60||age< -5", self.script)
        self.assertIn('if(stale){clearWatcherKioxia("データ停止', self.script)
        self.assertIn("Infinity", self.script)

    def test_disconnected_watcher_clears_previous_prices_and_signals(self):
        self.assertIn(
            'clearWatcherKioxia("Excel Watcher未接続・売買利用禁止"',
            self.script,
        )
        self.assertIn('"kio-watcher-entry":"条件未成立"', self.script)
        self.assertIn('"kio-watcher-signal":"無効・データ待ち"', self.script)

    def test_fresh_watcher_updates_signal_field_not_just_status_badge(self):
        self.assertIn('put("kio-watcher-signal",w.signal||"判定待ち")', self.script)


if __name__ == "__main__":
    unittest.main()
