import os
import unittest
from tests.ms2_poll_latency import run
@unittest.skipUnless(os.name=='nt','Native PS5.1 requires Windows')
class NativePollTests(unittest.TestCase):
    def test_accepted_drop_and_gate_busy_are_separate(self):
        for mode in ('accepted','drop','gate_busy'):
            r=run(mode,n=12)
            self.assertTrue(r['ps'].startswith('5.1.'))
            self.assertEqual(r['mock_counts'],[12,12,12])
            self.assertEqual(r['close_state'],'NOT_CLOSED')
            self.assertEqual(r['five_ms'],'NOT_MET')
            if mode=='gate_busy':self.assertEqual(r['cohorts']['GATE_BUSY']['full_ms']['N'],12)
            if mode=='drop':self.assertEqual(r['cohorts']['steady_DROP']['full_ms']['N'],12)
