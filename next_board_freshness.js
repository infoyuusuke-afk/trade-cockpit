/* NEXT board freshness. Display gate only. No orders and no market data calls. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.evaluateNextBoardFreshness = api.evaluateNextBoardFreshness;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var DEFAULTS = {
    ttlSeconds: 180,
    futureSkewSeconds: 30,
    sessionTimeZone: "Asia/Tokyo",
    requireSameSessionDate: true
  };

  function numberOr(primary, fallback, hardDefault) {
    if (typeof primary === "number" && Number.isFinite(primary)) return primary;
    if (typeof fallback === "number" && Number.isFinite(fallback)) return fallback;
    return hardDefault;
  }

  function parseTimestamp(value) {
    if (typeof value !== "string" || !value) return {ok: false, code: "MISSING_TIMESTAMP"};
    if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return {ok: false, code: "NAIVE_TIMESTAMP"};
    var ms = Date.parse(value);
    if (!Number.isFinite(ms)) return {ok: false, code: "INVALID_TIMESTAMP"};
    return {ok: true, ms: ms};
  }

  function sessionDate(ms, timeZone) {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit"
    }).format(new Date(ms));
  }

  function evaluateNextBoardFreshness(board, now, options) {
    options = options || {};
    var nowMs = now instanceof Date ? now.getTime() : (typeof now === "number" ? now : Date.parse(now));
    if (!board || typeof board !== "object") {
      return {ok: false, code: "MISSING_BOARD", message: "STALE：判定データがありません"};
    }
    if (board.source_mode === "sample" && !options.allowSample) {
      return {ok: false, code: "SAMPLE_NOT_PRODUCTION", message: "サンプル順位は本番のNEXTとして表示しません"};
    }
    if (board.source_mode === "unconfigured" || board.fail_closed_reason === "LIVE_SOURCE_NOT_CONFIGURED") {
      return {
        ok: false,
        code: "LIVE_SOURCE_NOT_CONFIGURED",
        message: board.fail_closed_reason || "LIVE_SOURCE_NOT_CONFIGURED"
      };
    }
    var parsed = parseTimestamp(board.generated_at);
    if (!parsed.ok) {
      var missing = parsed.code === "MISSING_TIMESTAMP"
        ? "STALE：判定時刻のないデータは表示しません"
        : "STALE：タイムゾーンのない、または不正な判定時刻は無効です";
      return {ok: false, code: parsed.code, message: missing};
    }
    if (!Number.isFinite(nowMs)) {
      return {ok: false, code: "INVALID_NOW", message: "STALE：現在時刻を確定できないため表示しません"};
    }
    var freshness = board.freshness || {};
    var ttl = numberOr(options.ttlSeconds, freshness.ttl_seconds, DEFAULTS.ttlSeconds);
    var skew = numberOr(options.futureSkewSeconds, freshness.future_skew_seconds, DEFAULTS.futureSkewSeconds);
    var timeZone = options.sessionTimeZone || freshness.session_timezone || DEFAULTS.sessionTimeZone;
    var requireDate = options.requireSameSessionDate;
    if (requireDate === undefined) {
      requireDate = freshness.require_same_session_date;
    }
    if (requireDate === undefined) requireDate = DEFAULTS.requireSameSessionDate;
    var age = (nowMs - parsed.ms) / 1000;
    if (age < -skew) {
      return {ok: false, code: "FUTURE_INVALID", message: "STALE：未来の判定時刻は無効です"};
    }
    if (requireDate && sessionDate(parsed.ms, timeZone) !== sessionDate(nowMs, timeZone)) {
      return {ok: false, code: "SESSION_EXPIRED", message: "STALE：前日または別セッションの判定は表示しません"};
    }
    if (age > ttl) {
      return {ok: false, code: "TTL_EXPIRED", message: "STALE：判定時刻が有効期限を超えています"};
    }
    return {ok: true, code: "FRESH", ageSeconds: age};
  }

  return {evaluateNextBoardFreshness: evaluateNextBoardFreshness};
});
