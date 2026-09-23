import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  envelope, validate, run, REPO, ISSUE, GPT_ACTOR_ID, GPT_APP_ID, GPT_APP_OWNER_ID, HANDOFF_PATH,
} from '../scripts/routine_bridge.mjs';

const now = Date.parse('2026-09-22T03:00:00Z');
function fixture() {
  const p = {
    main_sha: 'a'.repeat(40),
    task_id: 'C-117-review-1',
    text: 'Review public tests and open a Draft PR.',
  };
  const created = new Date(now).toISOString();
  const e = {
    action: 'created',
    repository: { full_name: REPO, default_branch: 'main' },
    issue: { number: ISSUE, state: 'open' },
    sender: { id: GPT_ACTOR_ID },
    comment: {
      id: 456,
      user: { id: GPT_ACTOR_ID },
      created_at: created,
      updated_at: created,
      body: envelope(p),
    },
  };
  const env = {
    BRIDGE_ENABLED: 'true',
    GITHUB_EVENT_NAME: 'issue_comment',
    GITHUB_RUN_ATTEMPT: '1',
    GITHUB_REPOSITORY: REPO,
    GITHUB_SHA: p.main_sha,
    ROUTINE_ID: 'trig_test',
    ROUTINE_TOKEN: 'test-only-token',
    GH_TOKEN: 'test-only-gh',
  };
  return { p, e, env };
}
function app(id = GPT_APP_ID, ownerId = GPT_APP_OWNER_ID) {
  return { id, owner: { id: ownerId } };
}
function mock(e, options = {}, refs = new Set()) {
  const calls = [];
  const fetcher = async (url, init = {}) => {
    calls.push({ url, init });
    const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
    if (url.includes('api.anthropic.com')) {
      if (options.timeout) throw new Error('sensitive transport detail');
      return reply(options.status || 200,
        options.badResponse ? {} : { type: 'routine_fire', claude_code_session_id: 'session_test' });
    }
    if (url.endsWith('issues/comments/456')) {
      const base = { ...e.comment, performed_via_github_app: app() };
      return reply(200, { ...base, ...options.comment });
    }
    if (url.endsWith(`issues/${ISSUE}`)) return reply(200, { state: options.closed ? 'closed' : 'open' });
    if (url.includes(`contents/${HANDOFF_PATH}?ref=`)) {
      const handoff = '# GPT / Cloud Shared Progress Handoff\nupdated_by: GPT\n';
      return reply(200, { type: 'file', encoding: 'base64', content: Buffer.from(handoff).toString('base64') });
    }
    if (url.endsWith('branches/main')) {
      return reply(200, {
        protected: options.unprotected ? false : true,
        commit: { sha: options.main || 'a'.repeat(40) },
      });
    }
    if (url.endsWith('git/refs')) {
      const { ref } = JSON.parse(init.body);
      if (options.claimFailure || refs.has(ref)) return reply(422, {});
      refs.add(ref);
      return reply(201, {});
    }
    throw new Error('unexpected URL');
  };
  return { fetcher, calls, refs, fires: () => calls.filter(c => c.url.includes('api.anthropic.com')) };
}

test('valid GitHub App provenance, fixed API contract, claims before POST, no redirects', async () => {
  const { e, env } = fixture(); const m = mock(e);
  assert.match(await run(e, env, m.fetcher, now), /^ACCEPTED/);
  assert.equal(m.refs.size, 2); assert.equal(m.fires().length, 1);
  const { url, init } = m.fires()[0];
  assert.equal(url, 'https://api.anthropic.com/v1/claude_code/routines/trig_test/fire');
  assert.equal(init.headers['anthropic-beta'], 'experimental-cc-routine-2026-04-01');
  assert.equal(init.headers['anthropic-version'], '2023-06-01');
  assert.equal(init.headers.Authorization, 'Bearer test-only-token');
  assert.equal(init.redirect, 'error');
  assert.deepEqual(Object.keys(JSON.parse(init.body)), ['text']);
});

const mutations = {
  disabled: f => f.env.BRIDGE_ENABLED = 'false',
  outsider: f => f.e.sender.id = 999,
  copiedByOutsider: f => f.e.comment.user.id = 999,
  ordinaryOwnerComment: f => f.e.comment.body = 'Please start Claude',
  oldSignedProtocol: f => f.e.comment.body = 'GPT-CLAUDE-NEXT-V1\nabc\ndef',
  edited: f => f.e.action = 'edited',
  modifiedTimestamp: f => f.e.comment.updated_at = '2026-09-22T03:01:00.000Z',
  staleComment: f => {
    const t = new Date(now - 15 * 60 * 1000).toISOString();
    f.e.comment.created_at = f.e.comment.updated_at = t;
  },
  futureComment: f => {
    const t = new Date(now + 1).toISOString();
    f.e.comment.created_at = f.e.comment.updated_at = t;
  },
  wrongIssue: f => f.e.issue.number = 172,
  prComment: f => f.e.issue.pull_request = {},
  closed: f => f.e.issue.state = 'closed',
  push: f => f.env.GITHUB_EVENT_NAME = 'push',
  pr: f => f.env.GITHUB_EVENT_NAME = 'pull_request',
  rerun: f => f.env.GITHUB_RUN_ATTEMPT = '2',
  fork: f => f.env.GITHUB_REPOSITORY = 'attacker/trade-cockpit',
  wrongRepo: f => f.e.repository.full_name = 'attacker/trade-cockpit',
  extraLines: f => f.e.comment.body += '\nadditional instructions',
  staleSHA: f => f.env.GITHUB_SHA = 'b'.repeat(40),
  oversized: f => {
    f.p.text = 'x'.repeat(8001);
    f.e.comment.body = [
      'GPT-CLAUDE-NEXT-V2',
      `main_sha: ${f.p.main_sha}`,
      `task_id: ${f.p.task_id}`,
      `text: ${f.p.text}`,
    ].join('\n');
  },
  unsafeRoutine: f => f.env.ROUTINE_ID = 'trig_x/../../evil',
};
for (const [name, mutate] of Object.entries(mutations)) {
  test(`reject ${name} before network`, async () => {
    const f = fixture(); mutate(f); const m = mock(f.e);
    await assert.rejects(run(f.e, f.env, m.fetcher, now));
    assert.equal(m.calls.length, 0);
  });
}

test('envelope rejects multiline instructions', () => {
  const { p } = fixture();
  assert.throws(() => envelope({ ...p, text: 'line one\nline two' }));
});

for (const [name, options] of Object.entries({
  changedComment: { comment: { body: 'changed' } },
  changedCreatedTime: { comment: { created_at: '2026-09-22T02:59:59.000Z' } },
  liveOwnerMismatch: { comment: { user: { id: 999 } } },
  manualOwnerNoApp: { comment: { performed_via_github_app: null } },
  claudeSameOwner: { comment: { performed_via_github_app: app(1236702, 196000000) } },
  wrongAppOwner: { comment: { performed_via_github_app: app(GPT_APP_ID, 999) } },
  mainMoved: { main: 'b'.repeat(40) },
  mainUnprotected: { unprotected: true },
  issueClosed: { closed: true },
  claimDenied: { claimFailure: true },
})) {
  test(`live validation fails closed: ${name}`, async () => {
    const { e, env } = fixture(); const m = mock(e, options);
    await assert.rejects(run(e, env, m.fetcher, now));
    assert.equal(m.fires().length, 0);
  });
}

for (const options of [
  { timeout: true }, { status: 429 }, { status: 500 }, { status: 302 }, { badResponse: true }, { status: 401 },
]) {
  test(`unknown/error retained and never retried: ${JSON.stringify(options)}`, async () => {
    const { e, env } = fixture(); const m = mock(e, options);
    await assert.rejects(run(e, env, m.fetcher, now)); assert.equal(m.fires().length, 1);
    await assert.rejects(run(e, env, m.fetcher, now)); assert.equal(m.fires().length, 1);
    assert.equal(m.refs.size, 2);
  });
}

test('concurrent deliveries create at most one session', async () => {
  const { e, env } = fixture(); const m = mock(e);
  const results = await Promise.allSettled([run(e, env, m.fetcher, now), run(e, env, m.fetcher, now)]);
  assert.equal(results.filter(r => r.status === 'fulfilled').length, 1);
  assert.equal(m.fires().length, 1);
});

test('new task in same budget bucket blocked; consumed task IDs cannot replay later', async () => {
  const { e, env, p } = fixture(); const m = mock(e); await run(e, env, m.fetcher, now);

  const other = structuredClone(e);
  other.comment.body = envelope({ ...p, task_id: 'another-task' });
  const m2 = mock(other, {}, m.refs);
  await assert.rejects(run(other, env, m2.fetcher, now));
  assert.equal(m2.fires().length, 0);
  assert.equal(m.refs.size, 3);

  const later = now + 21600000;
  const replay = structuredClone(e);
  replay.comment.created_at = replay.comment.updated_at = new Date(later).toISOString();
  replay.comment.body = envelope(p);
  const m3 = mock(replay, {}, m.refs);
  await assert.rejects(run(replay, env, m3.fetcher, later));
  assert.equal(m3.fires().length, 0);
});

test('workflow is main-only, protected-only, and contains no signing-key dependency', () => {
  const yml = readFileSync(new URL('../.github/workflows/gpt-claude-routine.yml', import.meta.url), 'utf8');
  assert.match(yml, /types: \[created\]/);
  assert.doesNotMatch(yml, /^  (push|pull_request|pull_request_target|workflow_dispatch|workflow_run|schedule):/m);
  assert.match(yml, /persist-credentials: false/);
  assert.match(yml, /github\.ref == 'refs\/heads\/main'/);
  assert.match(yml, /github\.ref_protected == true/);
  assert.match(yml, /format\('\{0\}', github\.event\.sender\.id\) == '307830101'/);
  assert.match(yml, /GPT-CLAUDE-NEXT-V2/);
  assert.doesNotMatch(yml, /GPT_PUBLIC_KEY|SIGNING_PRIVATE|GPT_REVIEWER_PUBLIC|GPT_REVIEWER_ACTOR_ID/);
  assert.doesNotMatch(yml, /run:.*\$\{\{/);
});

test('main loses protection after reservation: consumed attempt, zero fire', async () => {
  const { e, env } = fixture(); const m = mock(e); let reads = 0;
  const fetcher = async (url, init) => {
    if (url.endsWith('branches/main') && ++reads === 2) {
      return { ok: true, status: 200, json: async () => ({ protected: false, commit: { sha: 'a'.repeat(40) } }) };
    }
    return m.fetcher(url, init);
  };
  await assert.rejects(run(e, env, fetcher, now));
  assert.equal(m.refs.size, 2); assert.equal(m.fires().length, 0);
});

test('main changes after reservation: consumed attempt, zero fire', async () => {
  const { e, env } = fixture(); const m = mock(e); let reads = 0;
  const fetcher = async (url, init) => {
    if (url.endsWith('branches/main') && ++reads === 2) {
      return { ok: true, status: 200, json: async () => ({
        protected: true, commit: { sha: 'b'.repeat(40) },
      }) };
    }
    return m.fetcher(url, init);
  };
  await assert.rejects(run(e, env, fetcher, now));
  assert.equal(m.refs.size, 2); assert.equal(m.fires().length, 0);
});

test('uncertain claim write stops before fire and is not retried', async () => {
  const { e, env } = fixture(); const m = mock(e); let writes = 0;
  const fetcher = async (url, init) => {
    const response = await m.fetcher(url, init);
    if (url.endsWith('git/refs')) { writes++; throw new Error('timeout after server accepted ref'); }
    return response;
  };
  await assert.rejects(run(e, env, fetcher, now));
  assert.equal(writes, 1); assert.equal(m.refs.size, 1); assert.equal(m.fires().length, 0);
});


test('Claude fire is pinned to canonical shared handoff on attested main', async () => {
  const { e, env } = fixture(); const m = mock(e);
  await run(e, env, m.fetcher, now);
  const handoffReads = m.calls.filter(c => c.url.includes(`contents/${HANDOFF_PATH}?ref=${env.GITHUB_SHA}`));
  assert.equal(handoffReads.length, 1);
  const body = JSON.parse(m.fires()[0].init.body).text;
  assert.match(body, /Canonical progress handoff:/);
  assert.match(body, /Read it before any continuation work/);
  assert.match(body, /reconcile your branch\/Draft PR result back into that handoff/);
});
