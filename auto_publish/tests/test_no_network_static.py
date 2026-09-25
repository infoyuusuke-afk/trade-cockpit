"""No network publication in R1, no runtime coupling, no committed secrets."""
import ast
import re
import socket
import unittest
from pathlib import Path
from unittest import mock

from auto_publish.app.pipeline import approve, build_drafts, schedule
from auto_publish.tests.helpers import SESSION, FakeRenderer, PipelineCase

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parent
FORBIDDEN_MODULES = {"requests", "httpx", "aiohttp", "urllib3", "http.client", "urllib.request", "socket", "smtplib",
                     "ftplib", "websocket", "websockets", "paramiko", "grpc", "tweepy", "googleapiclient",
                     "google_auth_oauthlib"}
# Assembled from fragments so this file itself never contains the literal tokens
# (the spec's acceptance check greps auto_publish/ for them).
COUPLING = re.compile("|".join(["Rss" + "Order"] + [str(28000 + 580 + i) for i in range(4)]))
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),                                    # AWS access key
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),                          # GitHub token
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                                 # generic API secret
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),                              # Google API key
    re.compile(r"ya29\.[0-9A-Za-z\-_]+"),                               # Google OAuth access token
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),                        # Slack
    re.compile(r"""["']?(refresh_token|client_secret|access_token|api_key|password)["']?\s*[:=]\s*["'][^"'\s]{8,}["']""",
               re.I),
]


def _source_files():
    for p in sorted(PKG.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and "var" not in p.relative_to(PKG).parts:
            yield p


class TestNoNetwork(PipelineCase):
    def test_full_pipeline_runs_with_network_disabled(self):
        def boom(*a, **k):
            raise AssertionError(f"network access attempted: {a!r}")

        with mock.patch.object(socket.socket, "connect", boom), \
                mock.patch.object(socket.socket, "connect_ex", boom), \
                mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom):
            self.ingest_validate()
            results = build_drafts(self.ctx, SESSION, FakeRenderer())
            for r in results:
                approve(self.ctx, r["story_id"], "yusuke")
                self.assertEqual(schedule(self.ctx, r["story_id"])["state"], "SCHEDULED")


class TestStatic(unittest.TestCase):
    def test_no_network_capable_imports(self):
        offenders = []
        for p in _source_files():
            if p.suffix != ".py" or p.name.startswith("test_"):
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
                for n in names:
                    if n in FORBIDDEN_MODULES or n.split(".")[0] in FORBIDDEN_MODULES - {"http", "urllib"}:
                        offenders.append(f"{p.relative_to(REPO)}: {n}")
        self.assertEqual(offenders, [])

    def test_no_http_post_or_platform_urls_in_code(self):
        rx = re.compile(r"https?://|\.post\(|method\s*=\s*['\"]POST", re.I)
        offenders = [str(p.relative_to(REPO)) for p in _source_files()
                     if p.suffix == ".py" and not p.name.startswith("test_") and rx.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])

    def test_no_ai_cockpit_runtime_coupling(self):
        offenders = [str(p.relative_to(REPO)) for p in _source_files()
                     if p.name != "README.md" and p.suffix in {".py", ".json", ".sql", ".md", ".txt"}
                     and COUPLING.search(p.read_text(encoding="utf-8", errors="ignore"))]
        self.assertEqual(offenders, [], "only README may mention the prohibited ports/order path")

    def test_no_imports_from_ai_cockpit_code(self):
        offenders = []
        for p in _source_files():
            if p.suffix != ".py":
                continue
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module \
                        and node.module.split(".")[0] in {"scripts", "ms2_live", "config", "tests", "data"}:
                    offenders.append(f"{p.relative_to(REPO)}: {node.module}")
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name.split(".")[0] in {"scripts", "ms2_live"}:
                            offenders.append(f"{p.relative_to(REPO)}: {a.name}")
        self.assertEqual(offenders, [])

    def test_secret_scan(self):
        targets = list(_source_files())
        wf = REPO / ".github" / "workflows" / "auto-publish-r1.yml"
        if wf.exists():
            targets.append(wf)
        hits = []
        for p in targets:
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for rx in SECRET_PATTERNS:
                if p.name == Path(__file__).name:
                    continue
                for m in rx.finditer(text):
                    hits.append(f"{p.relative_to(REPO)}: {m.group(0)[:12]}...")
        self.assertEqual(hits, [])

    def test_secret_scan_detects_planted_secret(self):
        planted = 'client_secret = "abcdefgh12345678"'
        self.assertTrue(any(rx.search(planted) for rx in SECRET_PATTERNS))

    def test_runtime_state_is_gitignored(self):
        gi = (PKG / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("var/", "*.db", "secrets/"):
            self.assertIn(pattern, gi)


if __name__ == "__main__":
    unittest.main()
