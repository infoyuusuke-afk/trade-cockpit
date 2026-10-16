"""V10 startup must launch one UI tab without stopping the Brain backend.

Regression for OWNER Windows screenshots 2026-10-16 (Issue #387).
No MS2 / Excel / browser is started by these source contract tests.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / 'downloads' / 'AI_COCKPIT_CONTROLLER_V10.ps1'
START_CMD = ROOT / 'downloads' / 'START_AI_COCKPIT_V10.cmd'


class V10SingleBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = CONTROLLER.read_text(encoding='utf-8-sig')
        cls.launcher = START_CMD.read_text(encoding='utf-8-sig')

    def test_exactly_one_browser_target(self):
        matches = re.findall(r'^\s*Start-Process\s*\(\s*"http://127\.0\.0\.1:"\s*\+\s*\$PORT_\w+\s*\+\s*"[^"]+"\s*\)', self.script, re.M | re.I)
        self.assertEqual(len(matches), 1, matches)
        self.assertIn('$PORT_GATEWAY + "/?live=1"', matches[0])
        self.assertNotIn('Start-Process ("http://127.0.0.1:" + $PORT_BRAIN', self.script)

    def test_brain_server_still_starts_and_becomes_ready(self):
        for source in (
            '$brainGatewayProc = Start-Worker -Name "brain_gateway"',
            '$state.brain_gateway_pid = [int]$brainGatewayProc.Id',
            'Wait-PortBounded $PORT_BRAIN 20 "BrainGateway"',
            '$PORT_BRAIN = 28584',
            '$PORT_GATEWAY = 28581',
        ):
            self.assertIn(source, self.script)

    def test_cmd_does_not_open_another_browser(self):
        self.assertIn('RUN_AI_COCKPIT_V10.ps1', self.launcher)
        self.assertNotIn('http://127.0.0.1:', self.launcher.lower())
        self.assertNotRegex(self.launcher.lower(), r'\b(start|explorer)\b\s+"?https?://')

    def test_not_touching_order_or_state_protection(self):
        self.assertIn('REAL_SUBMIT_ALLOWED', self.script.upper())
        self.assertIn('FAIL_CLOSED', self.script.upper())
        self.assertIn('Starting Gateway first', self.script)


if __name__ == '__main__':
    unittest.main()
