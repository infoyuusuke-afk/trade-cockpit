#!/usr/bin/env python3
"""C-191 behavior-state primitives. Research/advisory only; no order actions."""
from __future__ import annotations

def excursion(side,entry,high,low):
    if not entry:return {"mae_pct":None,"mfe_pct":None}
    if side=="LONG":
        return {"mae_pct":(low/entry-1)*100,"mfe_pct":(high/entry-1)*100}
    if side=="SHORT":
        return {"mae_pct":(entry/high-1)*100,"mfe_pct":(entry/low-1)*100}
    return {"mae_pct":None,"mfe_pct":None}

def market_structure(last,vwap,or5_low,or5_high):
    ev=[]
    if vwap is not None: ev.append("above_vwap" if last>=vwap else "below_vwap")
    if or5_low is not None and last>=or5_low: ev.append("or5_low_reclaimed")
    if or5_high is not None and last>=or5_high: ev.append("or5_high_reclaimed")
    return ev

def coach_message(event_type,evidence):
    facts="、".join(evidence) if evidence else "市場構造を再確認"
    if event_type=="rapid_adverse_move":
        return f"急な逆行です。予想を守らず、まずリスクを確認しよう。現在の事実: {facts}。"
    if event_type=="breakeven_recovery":
        return f"建値に戻って安心して手放したくなる場面かもしれません。建値ではなく市場構造を見よう。現在の事実: {facts}。"
    if event_type=="post_exit_flip":
        return f"決済直後です。さっきの損益と次の方向は別です。売り買いを決める前に再評価しよう。現在の事実: {facts}。"
    return f"判断を急がず事実を確認しよう。現在の事実: {facts}。"
