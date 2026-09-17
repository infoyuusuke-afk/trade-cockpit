(() => {
  const section = document.getElementById('next-theme-radar');
  if (!section) return;
  const target = document.getElementById('next-theme-content');
  const meta = document.getElementById('next-theme-meta');
  const text = value => String(value ?? '—');
  const el = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text(value);
    return node;
  };
  const localCodes = new Map();
  const render = report => {
    target.replaceChildren();
    meta.textContent = `更新 ${text(report.updated_at)}｜ニュース集約は一次資料ではありません。実発注OFF。`;
    const themes = (report.themes || []).filter(x => x.status !== 'NO_EVENT');
    if (!themes.length) {
      target.append(el('p', 'next-theme-evidence', '新しい検知はありません。海外ニュース・市場反応を確認中です。'));
      return;
    }
    for (const theme of themes) {
      const card = el('article', 'next-theme-card' + (theme.emergency_display ? ' emergency' : ''), '');
      const top = el('div', 'next-theme-top', '');
      top.append(el('strong', '', `${theme.emergency_display ? '緊急監視｜' : ''}${theme.theme}｜${theme.status}`));
      top.append(el('span', 'next-theme-score', `${theme.score}/100`));
      card.append(top);
      const evidence = theme.evidence || {};
      card.append(el('p', 'next-theme-evidence', `海外ニュース ${evidence.news_fresh ? '取得' : '未取得'}／資金流入 ${evidence.money_flow_fresh ? '取得' : '未取得'}／TradingView ${evidence.tv_fresh ? '新鮮' : '未取得・古い'}／市場反応 ${theme.reacting_stock_count || 0}銘柄`));
      if (theme.status !== 'CONFIRMED') card.append(el('p', 'next-theme-warning', '監視候補です。未確認の条件があり、売買判断には使えません。'));
      const stocks = el('div', 'next-theme-stocks', '');
      for (const stock of theme.stocks || []) {
        const item = el('div', 'next-theme-stock', `${stock.group}｜${stock.code} ${stock.name}`);
        item.append(el('small', '', `${stock.type}｜市場反応 ${stock.market_reaction_verified ? '確認' : '未確認'}`));
        const local = localCodes.get(stock.code);
        if (local) item.append(el('small', 'next-theme-local', `MS2: ${text(local.signal)}｜FLOW: ${text(local.flow_bias)}`));
        stocks.append(item);
      }
      card.append(stocks);
      card.append(el('small', '', `最初の検知 ${text(theme.first_seen)}｜最終ニュース ${text(theme.last_event_at)}`));
      target.append(card);
    }
  };
  let report = null;
  const clearLocal = () => {
    if (!localCodes.size) return;
    localCodes.clear();
    if (report) render(report);
  };
  const load = async () => {
    try {
      const response = await fetch(`next_theme_radar.json?t=${Date.now()}`, {cache: 'no-store'});
      if (!response.ok) throw Error('radar unavailable');
      report = await response.json();
      render(report);
    } catch (_) {
      meta.textContent = 'NEXT THEME RADAR：データ未接続。売買禁止。';
    }
  };
  const local = async () => {
    try {
      const response = await fetch(`http://127.0.0.1:28580/live_ms2.json?t=${Date.now()}`, {cache: 'no-store'});
      if (!response.ok) { clearLocal(); return; }
      const data = await response.json();
      const at = new Date(String(data.updated_at || '').replace(' ', 'T') + '+09:00');
      const age = Date.now() - at.getTime();
      if (data.stale || !Number.isFinite(age) || age < 0 || age > 60000) {
        clearLocal();
        return;
      }
      localCodes.clear();
      for (const row of data.all_targets || []) {
        const code = String(row.ticker || '').replace(/\.T$/, '');
        if (code) localCodes.set(code, row);
      }
      if (report) render(report);
    } catch (_) { clearLocal(); }
  };
  load(); local(); setInterval(load, 60000); setInterval(local, 10000);
})();
