from scripts.ai_paper_candidate import validate_candidate,can_execute
def base():
 return {"candidate_source":"AI","planned_qty":100,"status":"LOCKED_PREOPEN","thesis":"x","invalidation":"y"}
def test_ai_lot_guard():
 x=base();x["planned_qty"]=200;assert validate_candidate(x)
def test_preopen_lock_cannot_execute():
 assert not can_execute(base())
def test_explicit_approval_still_required():
 x=base();x["status"]="APPROVED";assert can_execute(x)
