(() => {
  const $ = id => document.getElementById(id);
  const jstParts = date => Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short'
  }).formatToParts(date).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
  const jstDate = date => {
    const p = jstParts(date);
    return `${p.year}-${p.month}-${p.day}`;
  };
  const parseTimestamp = value => {
    if (typeof value !== 'string' || !value.trim()) return null;
    const normalized = value.trim().replace(' JST', '+09:00').replace(' ', 'T');
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  };
  const set = (id, value, tone = '') => {
    const node = $(id);
    if (!node) return;
    node.textContent = value;
    node.classList.remove('warn', 'ok', 'error');
    if (tone) node.classList.add(tone);
  };
  const fetchJson = async (url, timeoutMs = 3000) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url + (url.includes('?') ? '&' : '?') + 't=' + Date.now(), {
        cache: 'no-store', signal: controller.signal
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  };

  async function updateAcceptance() {
    try {
      const report = await fetchJson('phase6_status.json');
      const allowed = ['INSUFFICIENT_SAMPLE', 'FAIL_INTEGRITY', 'SHADOW_FORWARD_REVIEW_ELIGIBLE'];
      if (report.schema_version !== 1 || !allowed.includes(report.status) ||
          !Number.isInteger(report.forward_record_count) || report.forward_record_count < 0 ||
          !Number.isInteger(report.minimum_forward_records) || report.minimum_forward_records <= 0 ||
          !/^\d{4}-\d{2}-\d{2}$/.test(report.observed_date_jst) ||
          report.real_submit_allowed !== false) throw new Error('Invalid report');
      const snapshot = report.observed_date_jst !== jstDate(new Date());
      const count = `${report.forward_record_count} / ${report.minimum_forward_records}件`;
      const label = report.status === 'INSUFFICIENT_SAMPLE' ? 'サンプル不足' :
        report.status === 'FAIL_INTEGRITY' ? '整合性に問題' : 'レビュー対象';
      set('phase6-acceptance', `${label}・${count}`, report.status === 'FAIL_INTEGRITY' ? 'error' : 'warn');
      set('phase6-acceptance-time', `${report.observed_date_jst} JST時点${snapshot ? '／現在の件数は未確認' : ''}`);
      set('phase6-permission', '実発注 OFF', 'ok');
    } catch {
      set('phase6-acceptance', '検証状況を取得できません', 'error');
      set('phase6-acceptance-time', '実forward記録の件数は未確認');
      set('phase6-permission', '実発注状態を確認できません', 'error');
    }
  }

  async function updateDaily() {
    try {
      const data = await fetchJson('signals.json');
      const updated = parseTimestamp(data.updated_at);
      if (!updated) throw new Error('Missing timestamp');
      const p = jstParts(new Date());
      const today = `${p.year}-${p.month}-${p.day}`;
      const beforeFirstUpdate = `${p.hour}:${p.minute}` < '08:20';
      const weekend = p.weekday === 'Sat' || p.weekday === 'Sun';
      const sameDay = jstDate(updated) === today;
      const label = sameDay ? '本日更新' : (beforeFirstUpdate || weekend) ? '前営業日データ' : '更新待ち';
      set('phase6-daily', label, sameDay ? 'ok' : 'warn');
      set('phase6-daily-time', `最終更新 ${data.updated_at}`);
    } catch {
      set('phase6-daily', '更新時刻を確認できません', 'error');
      set('phase6-daily-time', '日次データの状態は未確認');
    }
  }

  async function updateMs2() {
    try {
      const data = await fetchJson('http://127.0.0.1:28580/live_ms2.json', 2500);
      const updated = parseTimestamp(data.updated_at);
      if (!updated || data.stale !== false || !Number.isInteger(data.valid) ||
          data.valid <= 0 || !Number.isInteger(data.universe) || data.universe <= 0 ||
          data.valid > data.universe || Date.now() - updated.getTime() > 60000 ||
          updated.getTime() - Date.now() > 10000) throw new Error('Stale local data');
      const p = jstParts(new Date());
      const minutes = Number(p.hour) * 60 + Number(p.minute);
      const marketHours = p.weekday !== 'Sat' && p.weekday !== 'Sun' &&
        ((minutes >= 540 && minutes <= 690) || (minutes >= 750 && minutes <= 930));
      set('phase6-ms2', `実機RSS ${data.valid}/${data.universe}銘柄${marketHours ? '' : '・時間外'}`, marketHours ? 'ok' : 'warn');
      set('phase6-ms2-time', `最終受信 ${data.updated_at}／60秒以内${marketHours ? '' : '／取引時間外'}`);
    } catch {
      set('phase6-ms2', '実機RSS 未接続・売買禁止', 'warn');
      set('phase6-ms2-time', '鮮度を確認できる実機データがありません');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!$('phase6-status')) return;
    updateAcceptance();
    updateDaily();
    updateMs2();
    setInterval(updateAcceptance, 60000);
    setInterval(updateDaily, 60000);
    setInterval(updateMs2, 15000);
  });
})();
