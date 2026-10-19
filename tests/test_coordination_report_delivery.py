from contextlib import closing
import copy
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from scripts import coordination_report_delivery as m


class API:
    def __init__(self):
        self.posts = 0
        self.remote = []
        self.fault = None
        self.actor = m.ACTOR
        self.sha = 'a' * 40
        self.conclusion = 'success'
        self.locked = False

    def comments(self):
        if self.fault == 'list':
            raise m.Blocked('READ_FAILED')
        return copy.deepcopy(self.remote)

    def request(self, path, method='GET', body=None):
        if method == 'POST':
            assert path == m.ISSUE + '/comments'
            self.posts += 1
            if self.fault == 'denied':
                raise m.Blocked('DENIED')
            comment = {'id': 123, 'body': body['body'], 'user': {'id': m.ACTOR},
                       'html_url': m.WEB + '/issues/282#issuecomment-123'}
            self.remote.append(comment)
            if self.fault == 'timeout':
                raise TimeoutError('secret must not escape')
            return copy.deepcopy(comment)
        if '/issues/comments/' in path:
            if self.fault == 'readback':
                raise OSError('read failure')
            return copy.deepcopy(self.remote[0])
        return {'user': {'id': self.actor},
                m.ROOT: {'full_name': m.REPO, 'private': False},
                m.ISSUE: {'number': 282, 'state': 'open', 'locked': self.locked},
                m.ROOT + '/pulls/447': {'state': 'open', 'draft': True,
                                      'head': {'sha': self.sha, 'repo': {'full_name': m.REPO}}},
                m.ROOT + '/actions/runs/12345': {'head_sha': self.sha, 'event': 'pull_request',
                                               'status': 'completed', 'conclusion': self.conclusion}}[path]


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'outbox.sqlite3'
        m.initialize(self.db)
        self.api = API()
        self.report = dict(sequence=1, head_sha='a' * 40, pr=447, ci_run=12345, state='SYNTHETIC_TESTED')

    def send(self, approve=True):
        digest = m.render(self.report)[2] if approve else None
        return m.deliver(self.api, self.db, self.report, digest)

    def test_success_then_duplicate_suppressed(self):
        self.assertTrue(self.send()['post_attempted'])
        self.assertFalse(self.send()['post_attempted'])
        self.assertEqual(self.api.posts, 1)

    def test_timeout_after_acceptance_reconciles_without_resend(self):
        self.api.fault = 'timeout'
        self.assertEqual(self.send()['state'], 'SEND_UNKNOWN')
        self.api.fault = None
        self.assertEqual(self.send(False)['state'], 'READ_VERIFIED')
        self.assertEqual(self.api.posts, 1)

    def test_denial_and_zero_remote_never_resend(self):
        self.api.fault = 'denied'
        self.assertEqual(self.send()['state'], 'SEND_UNKNOWN')
        self.api.fault = None
        self.assertEqual(self.send()['state'], 'SEND_UNKNOWN')
        self.assertEqual(self.api.posts, 1)

    def test_readback_failure_is_unknown(self):
        self.api.fault = 'readback'
        self.assertEqual(self.send()['state'], 'SEND_UNKNOWN')
        self.assertEqual(self.api.posts, 1)

    def test_claim_survives_crash_before_post(self):
        key, _, digest = m.render(self.report)
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute('INSERT INTO reports VALUES (?,?,?,?)', (key, digest, 'SEND_UNKNOWN', None))
        self.assertEqual(self.send()['state'], 'SEND_UNKNOWN')
        self.assertEqual(self.api.posts, 0)

    def test_claim_is_committed_before_post(self):
        original = self.api.request
        def request(path, method='GET', body=None):
            if method == 'POST':
                with closing(sqlite3.connect(self.db)) as con, con:
                    self.assertEqual(con.execute('SELECT state FROM reports').fetchone()[0], 'SEND_UNKNOWN')
            return original(path, method, body)
        self.api.request = request
        self.send()

    def test_concurrent_workers_share_outbox(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.send(), range(2)))
        self.assertEqual(self.api.posts, 1)
        self.assertTrue(any(r['state'] == 'READ_VERIFIED' for r in results))

    def test_exact_approval_required(self):
        with self.assertRaises(m.Blocked):
            self.send(False)
        with self.assertRaises(m.Blocked):
            m.deliver(self.api, self.db, self.report, '0' * 64)
        self.assertEqual(self.api.posts, 0)

    def test_incomplete_remote_read_blocks(self):
        self.api.fault = 'list'
        with self.assertRaises(m.Blocked):
            self.send()
        self.assertEqual(self.api.posts, 0)

    def test_wrong_actor_stale_sha_failed_ci_locked_issue(self):
        for field, value in [('actor', 9), ('sha', 'b' * 40), ('conclusion', 'failure'), ('locked', True)]:
            with self.subTest(field=field):
                self.api = API()
                setattr(self.api, field, value)
                with self.assertRaises(m.Blocked):
                    self.send()
                self.assertEqual(self.api.posts, 0)

    def test_remote_modified_spoofed_or_duplicate_blocks(self):
        self.send()
        original = copy.deepcopy(self.api.remote)
        for fault in ['body', 'actor', 'duplicate', 'url']:
            self.api.remote = copy.deepcopy(original)
            if fault == 'body':
                self.api.remote[0]['body'] += '\nchanged'
            elif fault == 'actor':
                self.api.remote[0]['user']['id'] = 9
            elif fault == 'url':
                self.api.remote[0]['html_url'] = 'https://example.com'
            else:
                self.api.remote += copy.deepcopy(original)
            with self.assertRaises(m.Blocked):
                self.send()
        self.assertEqual(self.api.posts, 1)

    def test_id_content_conflict(self):
        self.send()
        self.report['state'] = 'BLOCKED'
        with self.assertRaises(m.Blocked):
            self.send()

    def test_lost_outbox_and_reinitialization_fail_closed(self):
        with self.assertRaises(FileExistsError):
            m.initialize(self.db)
        self.db.unlink()
        with self.assertRaises(m.Blocked):
            self.send()
        self.assertEqual(self.api.posts, 0)

    def test_deleted_remote_after_success_does_not_repost(self):
        self.send()
        self.api.remote.clear()
        self.assertEqual(self.send()['state'], 'SEND_UNKNOWN')
        self.assertEqual(self.api.posts, 1)

    def test_privacy_allowlist_rejects_arbitrary_fields_values(self):
        for field, value in [('text', 'private account data'), ('head_sha', 'secret'),
                             ('state', 'GPT-CLAUDE-NEXT-V2'), ('ci_run', 'https://evil.invalid'),
                             ('sequence', True), ('pr', -1), ('state', ['BLOCKED'])]:
            with self.subTest(field=field, value=value):
                report = dict(self.report, **{field: value})
                with self.assertRaises(m.Blocked):
                    m.render(report)

    def test_duplicate_json_fields_rejected(self):
        with self.assertRaises(m.Blocked):
            m.strict_json('{"state":"BLOCKED","state":"IMPLEMENTED"}')

    def test_body_has_no_dispatch_or_approval(self):
        body = m.render(self.report)[1]
        self.assertNotIn('GPT-CLAUDE-NEXT-V2', body)
        self.assertIn('recipient_ack: NOT_VERIFIED', body)
        self.assertIn('real_submit_allowed: false', body)

    def test_pagination_checks_beyond_first_page(self):
        api = m.GitHub()
        with patch.object(api, 'request', side_effect=[[{}] * 100, [{'body': 'last'}]]) as read:
            self.assertEqual(len(api.comments()), 101)
            self.assertIn('page=2', read.call_args.args[0])

    def test_pagination_bound_fails_closed(self):
        api = m.GitHub()
        with patch.object(api, 'request', return_value=[{}] * 100):
            with self.assertRaises(m.Blocked):
                api.comments()

    def test_transport_never_retries_or_leaks_errors(self):
        with patch.object(m.subprocess, 'run', side_effect=OSError('credential')) as run:
            with self.assertRaisesRegex(m.Blocked, '^TRANSPORT_BLOCKED_OR_UNKNOWN$'):
                m.GitHub().request(m.ISSUE + '/comments', 'POST', {'body': 'safe'})
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
