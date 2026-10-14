import os
import unittest
from tests.ms2_concurrent_pipeline import run

class ConcurrentTests(unittest.TestCase):
    def test_real_bridge_writer_concurrent_faults(self):
        for mode in ('normal','delay','queue_full','gate_busy','permission','partial','before_replace','after_replace','worker_kill','kill','stop','duplicate','receipt_loss'):
            with self.subTest(mode=mode):
                r=run(mode,n=16)
                self.assertEqual(r['attempts'],16)
                self.assertEqual(r['queued']+r['drops'],16)
                self.assertEqual(r['close_state'],'NOT_CLOSED')
                self.assertEqual(r['production'],'P0_BLOCKED')
                self.assertEqual(r['five_ms'],'NOT_MET')
                self.assertEqual(sum(r['states'].values()),1 if mode=='duplicate' else 16)
                if mode=='gate_busy':self.assertGreater(r['cohorts']['GATE_BUSY']['full_ms']['N'],0)
    @unittest.skipUnless(os.name=='nt','Native Windows PS5.1 required')
    def test_native_real_bridge_concurrent(self):
        r=run('normal',n=16,native=True)
        self.assertEqual(r['ps'].split('.')[:2],['5','1'])
        self.assertTrue(r['concurrent_completion_observed'])
        self.assertEqual(r['states'].get('PERSISTED_VERIFIED'),r['queued'])

if __name__=='__main__':unittest.main()
