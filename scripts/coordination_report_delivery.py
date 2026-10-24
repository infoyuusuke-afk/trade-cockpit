"""Opt-in, single-outbox Issue #282 reporting. Never bypass a denied operation."""
from contextlib import closing
import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

REPO = 'infoyuusuke-afk/trade-cockpit'
ROOT = f'repos/{REPO}'
ISSUE = f'{ROOT}/issues/282'
WEB = f'https://github.com/{REPO}'
ACTOR = 307830101
STATES = {'IMPLEMENTED', 'SYNTHETIC_TESTED', 'BLOCKED', 'DELIVERY_PROBE'}


class Blocked(Exception):
    pass


def require(ok, reason):
    if not ok:
        raise Blocked(reason)


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_FIELD')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs)


def render(report):
    # No arbitrary narrative, paths, tokens, account data, URLs or instructions.
    require(type(report) is dict and set(report) == {'sequence', 'head_sha', 'pr', 'ci_run', 'state'}, 'SCHEMA')
    require(type(report['sequence']) is int and 1 <= report['sequence'] <= 999999, 'SEQUENCE')
    require(type(report['head_sha']) is str and re.fullmatch('[a-f0-9]{40}', report['head_sha']), 'SHA')
    for field in ('pr', 'ci_run'):
        require(type(report[field]) is int and 1 <= report[field] <= 10**14, 'EVIDENCE_ID')
    require(type(report['state']) is str and report['state'] in STATES, 'STATE')
    key = f"REPORT282-{report['pr']}-{report['head_sha']}-{report['sequence']}"
    body = '\n'.join([
        '[100B_REPORT_DELIVERY_V1]', f'message_id: {key}',
        'event_type: REPORT', 'sender_role_authenticated: false',
        f"state: {report['state']}", f"head_sha: {report['head_sha']}",
        f"draft_pr: {WEB}/pull/{report['pr']}",
        f"ci: {WEB}/actions/runs/{report['ci_run']}",
        'real_submit_allowed: false', 'stop_allowed: false', 'cutover_eligible: false',
        'recipient_ack: NOT_VERIFIED', 'production_verified: false',
        'Scope: source-code report only. No execution or approval is requested.',
    ])
    return key, body, hashlib.sha256(body.encode()).hexdigest()


class GitHub:
    def request(self, path, method='GET', body=None):
        # Fixed GitHub host and endpoints supplied only by this module. No shell,
        # fallback transport, credentials on argv, automatic retry or raw errors.
        command = ['gh', 'api', '--hostname', 'github.com', '--method', method, path]
        if body is not None:
            command += ['--input', '-']
        try:
            result = subprocess.run(command, input=json.dumps(body) if body else None,
                                    text=True, encoding='utf-8', capture_output=True, timeout=45)
            require(result.returncode == 0, 'TRANSPORT_BLOCKED_OR_UNKNOWN')
            return strict_json(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise Blocked('TRANSPORT_BLOCKED_OR_UNKNOWN') from None

    def comments(self):
        comments = []
        for page in range(1, 101):
            batch = self.request(f'{ISSUE}/comments?per_page=100&page={page}')
            require(type(batch) is list, 'INCOMPLETE_READ')
            comments.extend(batch)
            if len(batch) < 100:
                return comments
        raise Blocked('INCOMPLETE_READ')


def preflight(api, report):
    require(api.request('user').get('id') == ACTOR, 'ACTOR')
    repo = api.request(ROOT)
    require(repo.get('full_name') == REPO and repo.get('private') is False, 'REPOSITORY')
    issue = api.request(ISSUE)
    require(issue.get('number') == 282 and issue.get('state') == 'open'
            and not issue.get('locked') and 'pull_request' not in issue, 'ISSUE')
    pr = api.request(f"{ROOT}/pulls/{report['pr']}")
    require(pr.get('state') == 'open' and pr.get('draft') is True
            and pr.get('head', {}).get('sha') == report['head_sha']
            and pr.get('head', {}).get('repo', {}).get('full_name') == REPO, 'PR_EVIDENCE')
    run = api.request(f"{ROOT}/actions/runs/{report['ci_run']}")
    require(run.get('head_sha') == report['head_sha'] and run.get('event') == 'pull_request', 'CI_EVIDENCE')
    if report['state'] == 'SYNTHETIC_TESTED':
        require(run.get('status') == 'completed' and run.get('conclusion') == 'success', 'CI_NOT_PASS')


def verify_comment(comment, body):
    cid = comment.get('id')
    require(type(cid) is int and cid > 0 and comment.get('body') == body
            and comment.get('user', {}).get('id') == ACTOR
            and comment.get('html_url') == f'{WEB}/issues/282#issuecomment-{cid}', 'READBACK_MISMATCH')
    return comment['html_url']


def deliver(api, db, report, approved_digest=None):
    key, body, digest = render(report)
    # All workers MUST share this persistent local database. Cross-host dispatch
    # and a missing/recreated database are unsupported; no exactly-once claim.
    require(Path(db).is_file(), 'OUTBOX_MISSING')
    with closing(sqlite3.connect(db, timeout=10)) as con, con:
        con.execute('PRAGMA synchronous=FULL')
        con.execute('BEGIN IMMEDIATE')
        old = con.execute('SELECT digest,state,url FROM reports WHERE id=?', (key,)).fetchone()
        require(not old or old[0] == digest, 'ID_CONTENT_CONFLICT')
        preflight(api, report)
        matches = [c for c in api.comments() if f'message_id: {key}' in c.get('body', '')]
        if matches:
            require(len(matches) == 1, 'REMOTE_DUPLICATE')
            url = verify_comment(matches[0], body)
            verify_comment(api.request(f"{ROOT}/issues/comments/{matches[0]['id']}"), body)
            con.execute('INSERT OR REPLACE INTO reports VALUES (?,?,?,?)', (key, digest, 'READ_VERIFIED', url))
            return {'state': 'READ_VERIFIED', 'url': url, 'post_attempted': False}
        # A read returning zero is NOT proof that an uncertain write failed.
        if old:
            return {'state': 'SEND_UNKNOWN', 'post_attempted': False}
        require(approved_digest == digest, 'EXACT_BODY_APPROVAL_REQUIRED')
        con.execute('INSERT INTO reports VALUES (?,?,?,?)', (key, digest, 'SEND_UNKNOWN', None))
        con.commit()  # Durable before the only POST; crash/denial/timeout consumes it.
        try:
            sent = api.request(f'{ISSUE}/comments', 'POST', {'body': body})
            verify_comment(sent, body)
            live = api.request(f"{ROOT}/issues/comments/{sent['id']}")
            url = verify_comment(live, body)
        except Exception:
            # Never log exceptions: transport errors can contain credentials/data.
            return {'state': 'SEND_UNKNOWN', 'post_attempted': True}
        con.execute('UPDATE reports SET state=?,url=? WHERE id=?', ('READ_VERIFIED', url, key))
        return {'state': 'READ_VERIFIED', 'url': url, 'post_attempted': True}


def initialize(db):
    # Explicit initialization only; never silently replace a lost outbox.
    with open(db, 'xb'):
        pass
    with closing(sqlite3.connect(db)) as con, con:
        con.execute('CREATE TABLE reports (id TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, url TEXT)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'init', 'send', 'reconcile'])
    parser.add_argument('--report', type=Path)
    parser.add_argument('--outbox', type=Path, default=Path('data/private/report282.sqlite3'))
    parser.add_argument('--approved-sha256')
    args = parser.parse_args()
    try:
        if args.mode == 'init':
            initialize(args.outbox)
            print('OUTBOX_INITIALIZED')
            return
        require(args.report is not None, 'REPORT_REQUIRED')
        report = strict_json(args.report.read_text(encoding='utf-8-sig'))
        key, body, digest = render(report)
        if args.mode == 'prepare':
            print(json.dumps({'message_id': key, 'body': body, 'sha256': digest}, indent=2))
            return
        result = deliver(GitHub(), args.outbox, report,
                         args.approved_sha256 if args.mode == 'send' else None)
        print(json.dumps(result))
        if result['state'] != 'READ_VERIFIED':
            raise SystemExit(2)
    except Exception:
        print('BLOCKED: preserve outbox; inspect locally; do not switch transport or resend.')
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
