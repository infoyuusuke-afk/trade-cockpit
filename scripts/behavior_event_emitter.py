#!/usr/bin/env python3
"""C-191 presentation event builder. Advisory only; never routes orders."""
from datetime import datetime, timezone

COPY={
 "rapid_adverse_move":("reset","急な逆行です。予想を守らず、まずリスクと市場構造を確認しよう。"),
 "breakeven_recovery":("reassess","建値まで戻りました。安心感ではなく、ぶいわっぷとORの状態で再評価しよう。"),
 "relief_exit":("observe","決済しました。このあと価格がどう動くか記録して、安堵利確だったか後で検証します。"),
 "post_exit_flip":("reassess","決済直後です。さっきの損益と次の方向は別です。ゼロから再評価しよう。"),
 "liquidity_sweep":("reassess","安値を一度割ったあと戻しています。下抜け継続かリクレイムか、事実を確認しよう。"),
 "failed_breakdown":("reassess","下抜け後に水準を回復しています。建値ではなく市場構造を確認しよう。"),
 "reclaim":("reassess","重要水準を回復しています。出来高と維持時間を確認しよう。"),
}
def build_event(symbol,event_type,position_side,last_price,evidence,entry_price=None,mae_pct=None,mfe_pct=None,ts=None):
    mode,msg=COPY[event_type]
    return {"ts":ts or datetime.now(timezone.utc).isoformat(),"symbol":symbol,"event_type":event_type,
      "position_side":position_side,"entry_price":entry_price,"last_price":last_price,
      "mae_pct":mae_pct,"mfe_pct":mfe_pct,"or5_state":None,"or15_state":None,"vwap_state":None,
      "volume_state":None,"market_regime":None,"evidence":list(evidence),"coach_mode":mode,
      "coach_message":msg}
