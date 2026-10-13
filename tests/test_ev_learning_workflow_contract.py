"""EV Learning Loop must install its actual full-suite dependencies first."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EVLearningWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / ".github/workflows/ev-learning-loop.yml").read_text(encoding="utf-8")
        cls.mobile = (ROOT / ".github/workflows/mobile-control-tests.yml").read_text(encoding="utf-8")
        cls.requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    def test_dependencies_installed_before_safety_suite(self):
        install = "python -m pip install -r requirements.txt lxml"
        self.assertIn(install, self.workflow)
        self.assertLess(self.workflow.index(install), self.workflow.index("python -m unittest discover"))

    def test_dependency_contract_matches_known_green_ci(self):
        self.assertIn("pip install -r requirements.txt lxml", self.mobile)
        self.assertIn("pandas==", self.requirements)

    def test_ev_export_never_runs_if_tests_fail(self):
        self.assertLess(self.workflow.index("name: Safety tests"), self.workflow.index("name: Export labelled trade results"))
        self.assertNotIn("continue-on-error: true", self.workflow)

    def test_real_writer_environment_and_permissions_unchanged(self):
        self.assertIn("environment: main-data-writer", self.workflow)
        self.assertIn("contents: read", self.workflow)
        self.assertIn("ssh-key: ${{ secrets.MAIN_DATA_WRITER_DEPLOY_KEY }}", self.workflow)


if __name__ == "__main__":
    unittest.main()
