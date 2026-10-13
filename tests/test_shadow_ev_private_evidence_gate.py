import unittest
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from scripts.shadow_ev_private_evidence_gate import accept_private_roundtrip
from scripts.shadow_forward_evidence_chain import make_event,compute_chain_anchor
from scripts.shadow_forward_private_commit import CommitResult
from scripts.shadow_forward_persistence_pair import EvidenceAnchorPair

NOW=datetime(2026,10,13,10,0,tzinfo=timezone(timedelta(hours=9)))

def evidence():
    intent={"intent_hash":"i-1","strategy_id":"OR15_LONG","symbol":"285A.T","side":"BUY"}
    entry={"intent_hash":"i-1","strategy_id":"OR15_LONG","event_type":"ENTRY_FILL","evidence_source":"INDEPENDENT_OBSERVED_FILL","fill_id":"e-1","fill_price":100.0,"filled_qty":100,"observed_at":"2026-10-13T09:10:00+09:00"}
    exit_={"intent_hash":"i-1","strategy_id":"OR15_LONG","event_type":"EXIT_FILL","evidence_source":"INDEPENDENT_OBSERVED_FILL","fill_id":"x-1","fill_price":101.0,"filled_qty":100,"observed_at":"2026-10-13T09:30:00+09:00"}
    cost={"intent_hash":"i-1","cost_model_status":"VERIFIED","cost_pct":0.15}
    payloads=[("CAPTURE_START",{"intent":intent}),("LIFECYCLE_STEP",{"kind":"ENTRY_FILL","data":entry}),("LIFECYCLE_STEP",{"kind":"EXIT_FILL","data":exit_}),("LIFECYCLE_STEP",{"kind":"COST_VERIFIED","data":cost}),("FINALIZE",{"status":"CLOSED","research_only":True})]
    events=[];prev="0"*64
    for i,(t,p) in enumerate(payloads):
        event=make_event(event_type=t,captured_at=NOW-timedelta(seconds=5-i),payload=p,previous_hash=prev)
        events.append(event);prev=event["event_hash"]
    anchor=compute_chain_anchor(events)
    pair=EvidenceAnchorPair(CommitResult(Path("/private/proof.json"),True,True),CommitResult(Path("/private/anchor.json"),True,True),anchor,anchor)
    return events,pair

class PrivateEVGateTests(unittest.TestCase):
    def test_chain_and_pair_can_project_paper_only(self):
        events,pair=evidence();row,reason=accept_private_roundtrip(events,pair,now=NOW)
        self.assertIsNone(reason)
        self.assertFalse(row["real_submit_allowed"])
        self.assertEqual(row["strategy_key"],"OR15_LONG")

    def test_nondurable_evidence_blocks(self):
        events,pair=evidence()
        bad=EvidenceAnchorPair(CommitResult(Path("/private/proof.json"),True,False),pair.anchor,pair.evidence_anchor,pair.retained_anchor)
        self.assertEqual(accept_private_roundtrip(events,bad,now=NOW)[1],"HOLD_EVIDENCE_NOT_DURABLE")

    def test_nondurable_anchor_blocks(self):
        events,pair=evidence()
        bad=EvidenceAnchorPair(pair.evidence,CommitResult(Path("/private/anchor.json"),True,False),pair.evidence_anchor,pair.retained_anchor)
        self.assertEqual(accept_private_roundtrip(events,bad,now=NOW)[1],"HOLD_ANCHOR_NOT_DURABLE")

    def test_tampering_chain_blocks(self):
        events,pair=evidence();broken=deepcopy(events)
        broken[1]["payload"]["data"]["fill_price"]=999
        self.assertEqual(accept_private_roundtrip(broken,pair,now=NOW)[1],"FINALIZED_CHAIN_NOT_VERIFIED")

    def test_wrong_retained_anchor_blocks(self):
        events,pair=evidence()
        bad=EvidenceAnchorPair(pair.evidence,pair.anchor,pair.evidence_anchor,"a"*64)
        self.assertEqual(accept_private_roundtrip(events,bad,now=NOW)[1],"BLOCK_ANCHOR_MISMATCH")

    def test_unfinalized_chain_blocks(self):
        events,pair=evidence()
        self.assertEqual(accept_private_roundtrip(events[:-1],pair,now=NOW)[1],"FINALIZED_CHAIN_NOT_VERIFIED")

    def test_estimated_entry_even_on_valid_chain_rejected(self):
        events,_=evidence()
        events[1]["payload"]["data"]["evidence_source"]="SHADOW_MODEL"
        prev="0"*64;rebuilt=[]
        for e in events:
            nxt=make_event(event_type=e["event_type"],captured_at=e["captured_at"],payload=e["payload"],previous_hash=prev)
            rebuilt.append(nxt);prev=nxt["event_hash"]
        anchor=compute_chain_anchor(rebuilt)
        pair=EvidenceAnchorPair(CommitResult(Path("/private/proof.json"),True,True),CommitResult(Path("/private/anchor.json"),True,True),anchor,anchor)
        self.assertEqual(accept_private_roundtrip(rebuilt,pair,now=NOW)[1],"INDEPENDENT_FILL_EVIDENCE_MISSING")

    def test_unknown_cost_even_in_valid_chain_blocks(self):
        events,_=evidence()
        events[3]["payload"]["data"]["cost_model_status"]="UNKNOWN"
        rebuilt=[];prev="0"*64
        for e in events:
            next_=make_event(event_type=e["event_type"],captured_at=e["captured_at"],payload=e["payload"],previous_hash=prev)
            rebuilt.append(next_);prev=next_["event_hash"]
        anchor=compute_chain_anchor(rebuilt)
        pair=EvidenceAnchorPair(CommitResult(Path("/private/a"),True,True),CommitResult(Path("/private/b"),True,True),anchor,anchor)
        self.assertEqual(accept_private_roundtrip(rebuilt,pair,now=NOW)[1],"COST_EVIDENCE_NOT_VERIFIED")

    def test_same_artifact_as_anchor_rejected(self):
        events,pair=evidence()
        bad=EvidenceAnchorPair(pair.evidence,CommitResult(pair.evidence.path,True,True),pair.evidence_anchor,pair.retained_anchor)
        self.assertEqual(accept_private_roundtrip(events,bad,now=NOW)[1],"BLOCK_ANCHOR_NOT_SEPARATE")

if __name__=="__main__": unittest.main()
