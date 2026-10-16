import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from scripts.ms2_v10_receipt_reader import audit_files

NOW=datetime(2026,10,16,9,tzinfo=timezone.utc)
class ReceiptReader(unittest.TestCase):
    def test_missing_independent_receipts_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            gateway=root/"health.json"
            gateway.write_text(json.dumps({"runtime":{"fail_closed":False,"data_conflict":False,"price_source_status":"OK"}}),encoding="utf8")
            paths={name:str(root/(name+".json")) for name in ("collector","watcher","gateway","brain")}
            result=audit_files(gateway,paths,NOW.isoformat())
            self.assertEqual(result["status"],"BLOCKED")
            self.assertIn("SOURCE_RECEIPT_UNAVAILABLE_BRAIN",result["reasons"])
            self.assertFalse(result["real_submit_allowed"])
    def test_four_explicit_receipts_observation_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            gateway=root/"health.json"
            gateway.write_text(json.dumps({"runtime":{"fail_closed":False,"data_conflict":False,"price_source_status":"OK"}}))
            paths={}
            for name in ("collector","watcher","gateway","brain"):
                p=root/(name+".json")
                p.write_text(json.dumps({"state":"HEALTHY","updated_at":NOW.isoformat(),"last_data_at":(NOW-timedelta(seconds=2)).isoformat()}))
                paths[name]=str(p)
            result=audit_files(gateway,paths,NOW.isoformat())
            self.assertEqual(result["status"],"OBSERVATION_CANDIDATE_ONLY")
            self.assertFalse(result["source_authenticated"])
            self.assertFalse(result["real_submit_allowed"])
if __name__=="__main__":unittest.main()
