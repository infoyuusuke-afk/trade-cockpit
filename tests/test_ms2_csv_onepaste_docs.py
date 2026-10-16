"""Static guard against scripts, writes and raw data disclosure."""
from pathlib import Path
import re
import unittest

DOC = Path(__file__).resolve().parents[1] / 'docs' / 'MS2_CSV_READONLY_ONEPASTE.md'

class ManualCsvDiagnosticDocs(unittest.TestCase):
    def test_exactly_one_guarded_snippet(self):
        text = DOC.read_text(encoding='utf-8')
        delimiter = chr(96) * 3
        matches = re.findall(re.escape(delimiter) + r'powershell\n(.*?)\n' + re.escape(delimiter), text, re.S)
        self.assertEqual(len(matches), 1)
        cmd = matches[0]
        for forbidden in ('set-executionpolicy', 'unblock-file', 'out-file',
                          'set-content', 'add-content', 'remove-item',
                          'invoke-webrequest', 'invoke-restmethod', 'invoke-expression',
                          'http://', 'https://', 'writeallbytes', 'writealltext'):
            self.assertNotIn(forbidden, cmd.lower())
        for required in ('PASS_READONLY_FORMAT', 'BLOCKED: READONLY_FORMAT_OR_SOURCE',
                         'UNKNOWN_NO_DIAG', 'real_submit_allowed = $false',
                         'source_authenticated = $false',
                         'D:\\AI_Cockpit_Data\\MS2_CSV\\manual_backup\\kioxia_ticks_20261016.csv'):
            self.assertIn(required, cmd)

if __name__ == '__main__':
    unittest.main()
