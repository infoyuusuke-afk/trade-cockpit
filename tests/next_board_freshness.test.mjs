import assert from "node:assert/strict";
import test from "node:test";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {evaluateNextBoardFreshness} = require("../next_board_freshness.js");

const NOW = Date.parse("2026-10-01T10:15:00+09:00");

function board(overrides) {
  return Object.assign({
    generated_at: "2026-10-01T10:14:30+09:00",
    source_mode: "discovery",
    fail_closed: false,
    freshness: {
      ttl_seconds: 180,
      future_skew_seconds: 30,
      session_timezone: "Asia/Tokyo",
      require_same_session_date: true
    },
    next5: [{symbol: "A200", score: 79.7, state: "IGNITION", next_rank: 1}]
  }, overrides);
}

test("a fresh same-session snapshot is usable", () => {
  const verdict = evaluateNextBoardFreshness(board(), NOW);
  assert.equal(verdict.ok, true);
  assert.equal(verdict.code, "FRESH");
});

test("a snapshot older than the TTL is stale", () => {
  const verdict = evaluateNextBoardFreshness(board({generated_at: "2026-10-01T10:00:00+09:00"}), NOW);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.code, "TTL_EXPIRED");
  assert.match(verdict.message, /STALE/);
});

test("yesterday stays stale even when the TTL is longer than a day", () => {
  const verdict = evaluateNextBoardFreshness(board({
    generated_at: "2026-09-30T15:20:00+09:00",
    freshness: {ttl_seconds: 1000000, require_same_session_date: true, session_timezone: "Asia/Tokyo"}
  }), NOW);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.code, "SESSION_EXPIRED");
  assert.match(verdict.message, /STALE/);
});

test("a future timestamp beyond the skew is rejected", () => {
  const verdict = evaluateNextBoardFreshness(board({generated_at: "2026-10-01T10:20:00+09:00"}), NOW);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.code, "FUTURE_INVALID");
  assert.match(verdict.message, /STALE/);
});

test("a small future skew stays fresh", () => {
  const verdict = evaluateNextBoardFreshness(board({generated_at: "2026-10-01T10:15:10+09:00"}), NOW);
  assert.equal(verdict.ok, true);
});

test("a timestamp without a timezone is rejected", () => {
  const verdict = evaluateNextBoardFreshness(board({generated_at: "2026-10-01T10:15:00"}), NOW);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.code, "NAIVE_TIMESTAMP");
  assert.match(verdict.message, /STALE/);
});

test("a missing timestamp is rejected", () => {
  const verdict = evaluateNextBoardFreshness(board({generated_at: null}), NOW);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.code, "MISSING_TIMESTAMP");
});

test("sample output cannot pass as a production board", () => {
  const verdict = evaluateNextBoardFreshness(board({source_mode: "sample"}), NOW);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.code, "SAMPLE_NOT_PRODUCTION");
  assert.doesNotMatch(verdict.message, /A200/);
});
