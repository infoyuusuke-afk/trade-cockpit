import unittest
from unittest.mock import patch
from scripts.run_kioxia_dex_research_session import run
class RunnerTest(unittest.TestCase):
    @patch("subprocess.run")
    def test_subprocess_failure_is_fail_closed(self,m):
        m.side_effect=__import__("subprocess").CalledProcessError(1,["x"])
        with self.assertRaises(__import__("subprocess").CalledProcessError): run(["x"])
        assert m.call_args.kwargs["check"] is True
