"""OWNER 2026-10-27 「AIコクピットのコントロールタブに過去実績と俺の分析をいれて、おれをたたきなおしてくれ」「必ず後場にまけていた」.
The numbers live only on the OWNER's PC (RuntimeDir/owner_review_v1.json); the repo holds only the route and the screen."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_gateway_serves_the_local_review_file_with_safe_flags_only():
    ps = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
    body = ps.split("function Get-OwnerReviewView([string]$RuntimeDir) {", 1)[1].split("\nfunction ", 1)[0]
    assert "Join-Path $RuntimeDir 'owner_review_v1.json'" in body
    assert "'100b-v10-owner-review-v1'" in body and "$view.real_submit_allowed -ne $false" in body
    assert "$item.Length -gt 1048576" in body and "ReparsePoint" in body
    assert "if ($path -eq '/owner_review.json') {" in ps
    assert "'owner_review_v1.json'" not in ps.split("$allowedUiFiles = @(", 1)[1].split(")", 1)[0]


def test_control_tab_shows_the_review_and_the_owner_statement():
    js = (ROOT / "trade_control.js").read_text(encoding="utf-8")
    assert "<h2>あなたの過去実績（たたき直し）</h2>" in js
    assert 'const rv=await gJson("/owner_review.json");' in js
    assert "過去実績のファイルを読めません" in js
    assert "本人の申告：「" in js and "売買の指示ではありません" in js


def test_no_real_account_numbers_in_the_repo():
    assert not list(ROOT.rglob("owner_review_v1.json"))
