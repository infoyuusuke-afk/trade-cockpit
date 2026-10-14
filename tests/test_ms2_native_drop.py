import os
import unittest
from tests.ms2_native_drop_benchmark import run_case

@unittest.skipUnless(os.name=='nt','Native PowerShell 5.1 Windows only')
class NativeDropTests(unittest.TestCase):
    def test_native_capture_packing_submit_persist_reread(self):
        r=run_case(n=10)
        self.assertTrue(r['ps'].startswith('5.1.'))
        self.assertEqual(r['evidence']['snapshot']['total'],10)
        self.assertEqual(r['evidence']['tail'],'ACCOUNTED_TO_PRODUCER_COMPLETE')
        # ACCEPTED is queue-only; a cold/stale acquisition can be discarded.
        self.assertGreater(r['persisted'],0)
        accepted=r['ACCEPTED']['full_ms']['N']
        self.assertLessEqual(r['persisted'],accepted)
        self.assertEqual(r['evidence']['downstream']['accepted_not_persisted'],accepted-r['persisted'])
        self.assertEqual(r['jsonl_reread'],r['persisted'])
        self.assertEqual(r['mock_counts'],[10,10,10])
    def test_actual_producer_kill_before_and_after_acceptance(self):
        for pause in ('before_capture','after_accept'):
            r=run_case(n=5,pause=pause)
            self.assertEqual(r['evidence']['outcome'],'PRODUCER_CRASH')
            self.assertEqual(r['evidence']['tail'],'UNKNOWN')
            self.assertEqual(r['evidence']['snapshot']['total'],1)
            self.assertEqual(r['evidence']['snapshot_integrity'],'TORN_OR_INVALID')
    def test_queue_busy_kill_writer_and_generation_negative(self):
        for mode in ('queue_full','gate_busy','kill','writer_stopped','old_generation','corrupt'):
            r=run_case(mode,n=20)
            self.assertEqual(r['evidence']['close_state'],'NOT_CLOSED')
            self.assertEqual(r['evidence']['snapshot']['total'],20)
            self.assertGreater(r['DROP']['full_ms']['N'],0)
    def test_actual_drop_counters_survive_hard_killed_ps_producer(self):
        r=run_case('gate_busy',n=5,pause='after_drop')
        self.assertEqual(r['evidence']['outcome'],'PRODUCER_CRASH')
        self.assertEqual(r['evidence']['snapshot']['counters']['GATE_BUSY']['count'],2)
        self.assertEqual(r['evidence']['snapshot_integrity'],'VERIFIED')
        self.assertEqual(r['evidence']['tail'],'UNKNOWN')

if __name__=='__main__':unittest.main()
