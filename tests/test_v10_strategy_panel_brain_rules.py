"""OWNER 2026-10-27 「戦略別パフォーマンスをつないで」: the CONTROL strategy panel adds the brain's virtual results per
rule from /rule_shadow.json (count, EV after costs, win rate, PF, exits, the past-data halves), a comparison of the
rules with 20+ trades, and 未接続 (not 0) when the file cannot be read."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js():
    return (ROOT / "trade_control.js").read_text(encoding="utf-8")


def test_panel_appends_brain_rule_cards():
    js = _js()
    assert "strategy.innerHTML=controlPerformanceHtml(audit)+brainRuleHtml(await loadRuleShadow());" in js
    assert 'fetch("/rule_shadow.json?t="+Date.now(),{cache:"no-store"})' in js
    assert 'v.schema_version==="100b-v10-rule-shadow-v1"&&v.real_submit_allowed===false' in js


def test_unreadable_file_is_not_zero():
    js = _js()
    body = js.split("function brainRuleHtml(rs){", 1)[1].split("function executionHtml", 1)[0]
    assert '"SHADOW｜ブレインのルール別","未接続"' in body and "0件と断定しません" in body


def test_rule_cards_show_counts_ev_pf_and_halves():
    body = _js().split("function brainRuleHtml(rs){", 1)[1].split("function executionHtml", 1)[0]
    for k in ('["取引件数"', '["1回の期待値"', '["勝率"', '["PF"', '["決済の内訳"', '["過去データ 前半"', '["過去データ 後半"'):
        assert k in body
    assert 'n>=20?"記録N="+n:"N不足（"+n+"回）"' in body
    assert '"SHADOW｜ルールの相対強弱","N≥20"' in body and "ranked.length>=2" in body
