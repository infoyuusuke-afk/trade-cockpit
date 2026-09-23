from scripts.ai_paper_candidate import validate_candidate,can_execute
def base():
 return {"candidate_source":"AI","planned_qty":100,"status":"LOCKED_PREOPEN","thesis":"x","invalidation":"y"}
def test_ai_lot_guard():
 x=base();x["planned_qty"]=200;assert validate_candidate(x)
def test_ai_actual_lot_guard():
 x=base();x["status"]="EXECUTED";x["actual_qty"]=200
 assert "AI executed validation lot must be exactly 100 shares" in validate_candidate(x)
def test_ai_executed_100_share_record_is_valid():
 x=base();x["status"]="EXECUTED";x["actual_qty"]=100
 assert not validate_candidate(x)
def test_preopen_lock_cannot_execute():
 assert not can_execute(base())
def test_explicit_approval_still_required():
 x=base();x["status"]="APPROVED";assert can_execute(x)
def test_paper_only_cannot_execute():
 x=base();x["status"]="PAPER_ONLY";assert not can_execute(x)
def test_executed_record_cannot_request_new_execution():
 x=base();x["status"]="EXECUTED";x["actual_qty"]=100;assert not can_execute(x)
