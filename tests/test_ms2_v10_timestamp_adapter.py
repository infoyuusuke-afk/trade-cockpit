import unittest
from scripts.ms2_v10_timestamp_adapter import legacy_jst_to_utc,normalize_source_timestamp

class TimestampAdapter(unittest.TestCase):
    def test_explicit_jst_conversion(self):
        self.assertEqual(legacy_jst_to_utc("2026-10-16 09:00:00","collector","Asia/Tokyo"),"2026-10-16T00:00:00+00:00")
    def test_no_timezone_guess(self):
        with self.assertRaises(ValueError):
            normalize_source_timestamp("2026-10-16 09:00:00","watcher")
    def test_offset_aware_accepted(self):
        self.assertEqual(normalize_source_timestamp("2026-10-16T09:00:00+09:00","gateway"),"2026-10-16T00:00:00+00:00")
    def test_invalid_source_and_bad_time(self):
        with self.assertRaises(ValueError):
            legacy_jst_to_utc("2026-10-16 09:00:00","other","Asia/Tokyo")
        with self.assertRaises(ValueError):
            legacy_jst_to_utc("2026-10-16 99:00:00","brain","Asia/Tokyo")
if __name__=="__main__":unittest.main()
