import copy
import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts import coordination_intake as m
from scripts import coordination_report_delivery as delivery
from test_coordination_report_delivery import API


class Fixture:
    def __init__(self):
        self.api = API()
        self.grant = 'AUTHORIZED'
        self.acks = []
        self.authenticated = True
        self.receiver_read = True
        self.sender_read = True
        self.original_read = True
        self.changed = False
        self.list_error = False

    def authorize(self, event):
        return self.grant

    def deliver(self, db, event):
        report = event['report']
        return delivery.deliver(self.api, db, report, delivery.render(report)[2])['state']

    def report_readback(self, event):
        if not self.original_read:
            return False
        delivery.verify_comment(self.api.request(delivery.ROOT + '/issues/comments/123'),
                                delivery.render(event['report'])[1])
        return True

    def find_acks(self, key):
        if self.list_error:
            raise OSError('incomplete pagination')
        return copy.deepcopy(self.acks)

    def authenticated_run(self, role, run, url):
        return self.authenticated

    def get_ack(self, url):
        ack = self.acks[0]
        return 'edited' if self.changed else m.canonical({k: v for k, v in ack.items()
                                                        if k != 'body_sha256'})

    def receipt(self, role, run, url, digest, later_than):
        return self.sender_read if later_than else self.receiver_read


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'queue.sqlite'
        delivery.initialize(self.db)
        m.initialize(self.db)
        self.f = Fixture()
        self.q = m.SyntheticQueue(self.db, self.f)
        self.event = dict(event_id='event1', source_role='analyst', recipient_role='coordinator',
                          run_id='run1', report=dict(sequence=1, head_sha='a'*40, pr=447,
                                                     ci_run=12345, state='SYNTHETIC_TESTED'))

    def ready(self):
        self.q.intake(self.event)
        self.assertEqual(self.q.dispatch('event1')['state'], 'READ_VERIFIED')
        ack = dict(message_id='ack1', in_reply_to=delivery.render(self.event['report'])[0],
                   source_role='coordinator', recipient_role='analyst', run_id='receiver1',
                   url=delivery.WEB + '/issues/282#issuecomment-124')
        ack['body_sha256'] = hashlib.sha256(m.canonical(ack).encode()).hexdigest()
        self.f.acks = [ack]

    def test_production_default_closed(self):
        self.assertEqual(m.production_status()['state'], 'WRITE_UNAVAILABLE')
        self.assertFalse(m.production_status()['end_to_end_verified'])

    def test_concurrent_dispatch_one_post(self):
        self.q.intake(self.event)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.q.dispatch('event1'), range(8)))
        self.assertEqual(self.f.api.posts, 1)

    def test_duplicate_intake_and_dispatch(self):
        self.q.intake(self.event)
        self.q.intake(self.event)
        self.q.dispatch('event1')
        self.q.dispatch('event1')
        self.assertEqual(self.f.api.posts, 1)

    def test_conflicting_event_rejected(self):
        self.q.intake(self.event)
        self.event['report']['sequence'] = 2
        with self.assertRaises(m.Blocked):
            self.q.intake(self.event)

    def test_alias_message_rejected(self):
        self.q.intake(self.event)
        self.event['event_id'] = 'alias'
        with self.assertRaises(m.Blocked):
            self.q.intake(self.event)

    def test_denial_sticky_across_id_and_run_changes(self):
        self.f.grant = 'PLATFORM_SAFETY_DENIED'
        self.q.intake(self.event)
        self.f.grant = 'AUTHORIZED'
        self.event.update(event_id='event2', run_id='run2')
        self.event['report']['sequence'] = 2
        self.assertEqual(self.q.intake(self.event)['state'], 'WRITE_UNAVAILABLE')
        self.q.dispatch('event2')
        self.assertEqual(self.f.api.posts, 0)

    def test_missing_grant(self):
        self.f.grant = 'UNKNOWN'
        self.assertEqual(self.q.intake(self.event)['state'], 'WRITE_UNAVAILABLE')
        self.assertEqual(self.f.api.posts, 0)

    def test_revocation_before_dispatch(self):
        self.q.intake(self.event)
        self.f.grant = 'PLATFORM_SAFETY_DENIED'
        self.assertEqual(self.q.dispatch('event1')['state'], 'WRITE_UNAVAILABLE')
        self.assertEqual(self.f.api.posts, 0)

    def test_timeout_never_resends(self):
        self.q.intake(self.event)
        self.f.api.fault = 'timeout'
        self.assertEqual(self.q.dispatch('event1')['state'], 'SEND_UNKNOWN')
        self.f.api.fault = None
        self.q.dispatch('event1')
        self.assertEqual(self.f.api.posts, 1)
        with self.assertRaises(m.Blocked):
            self.q.verify_ack('event1')
        self.event.update(event_id='new_id', run_id='new_run')
        self.event['report']['sequence'] = 2
        self.assertEqual(self.q.intake(self.event)['state'], 'WRITE_UNAVAILABLE')
        self.q.dispatch('new_id')
        self.assertEqual(self.f.api.posts, 1)

    def test_missing_outbox_not_recreated(self):
        self.db.unlink()
        with self.assertRaises(m.Blocked):
            self.q.intake(self.event)
        self.assertFalse(self.db.exists())

    def test_untrusted_authorization_field_rejected(self):
        self.event['authorized'] = True
        with self.assertRaises(m.Blocked):
            self.q.intake(self.event)

    def test_full_synthetic_chain_never_real_e2e(self):
        self.ready()
        result = self.q.verify_ack('event1')
        self.assertEqual(result['state'], 'ACK_VERIFIED')
        self.assertEqual(result['evidence_class'], 'SYNTHETIC_ONLY')
        self.assertFalse(result['end_to_end_verified'])
        self.assertEqual(self.f.api.posts, 1)

    def test_missing_duplicate_wrong_direction_or_reply_ack(self):
        self.ready()
        original = copy.deepcopy(self.f.acks)
        variants = [[], original * 2]
        for field, value in [('source_role', 'analyst'), ('recipient_role', 'other'),
                             ('in_reply_to', 'wrong'), ('run_id', 'run1'),
                             ('url', 'https://example.com/ack')]:
            changed = copy.deepcopy(original)
            changed[0][field] = value
            variants.append(changed)
        for acks in variants:
            with self.subTest(acks=acks):
                self.f.acks = acks
                self.assertEqual(self.q.verify_ack('event1')['state'], 'HANDOFF_PENDING')

    def test_missing_independent_proof(self):
        self.ready()
        for field in ['authenticated', 'receiver_read', 'sender_read', 'original_read']:
            with self.subTest(field=field):
                setattr(self.f, field, False)
                self.assertEqual(self.q.verify_ack('event1')['state'], 'HANDOFF_PENDING')
                setattr(self.f, field, True)

    def test_edit_or_partial_read_revokes_prior_verification(self):
        self.ready()
        self.assertEqual(self.q.verify_ack('event1')['state'], 'ACK_VERIFIED')
        for field in ['changed', 'list_error']:
            setattr(self.f, field, True)
            self.assertEqual(self.q.verify_ack('event1')['state'], 'HANDOFF_PENDING')
            setattr(self.f, field, False)


if __name__ == '__main__':
    unittest.main()
