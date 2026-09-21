from pathlib import Path
import unittest
class RuntimePrivacyTests(unittest.TestCase):
 def test_ms2_runtime_is_gitignored(self):
  txt=Path(".gitignore").read_text(encoding="utf-8")
  self.assertIn("ms2_live/runtime/",txt)
