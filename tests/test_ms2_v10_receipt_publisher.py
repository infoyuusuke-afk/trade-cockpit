import tempfile
import unittest
from pathlib import Path
from scripts.ms2_v10_receipt_publisher import build_receipt,publish_new_receipt

class Publisher(unittest.TestCase):
    def test_no_timestamp_invention_and_explicit_source(self):
        with self.assertRaises(ValueError):
            build_receipt("collector","2026-10-16T10:00:00+09:00",None,"HEALTHY")
        with self.assertRaises(ValueError):
            build_receipt("invalid","2026-10-16T10:00:00+09:00","2026-10-16T09:59:59+09:00","HEALTHY")
    def test_new_file_only_and_no_overwrite(self):
        r=build_receipt("collector","2026-10-16T10:00:00+09:00","2026-10-16T09:59:59+09:00","HEALTHY")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"receipt.json"
            publish_new_receipt(r,p)
            original=p.read_bytes()
            with self.assertRaises(FileExistsError):
                publish_new_receipt(r,p)
            self.assertEqual(original,p.read_bytes())
    def test_bad_timestamp_order_blocked(self):
        with self.assertRaises(ValueError):
            build_receipt("brain","2026-10-16T09:00:00+09:00","2026-10-16T10:00:00+09:00","HEALTHY")
if __name__=="__main__":unittest.main()
