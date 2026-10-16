/* V10 publication status only. Never upgrades market trust or enables trades.
   Separate source-owned JSON publication time from actual MS2 tick timestamps. */
(function (root) {
  "use strict";
  function statusLabel(state) {
    switch (state) {
      case "RECENT_PUBLICATION_ONLY": return "60秒以内に発行（価格鮮度は未認証）";
      case "PUBLICATION_STALE": return "発行60秒超";
      case "PROCESS_UNVERIFIED": return "プロセス未検証";
      case "TIMESTAMP_FUTURE": return "時刻異常";
      case "TIMESTAMP_INVALID":
      case "TIMEZONE_UNVERIFIED":
      case "TIMESTAMP_MISSING": return "日時未検証";
      default: return "未確認";
    }
  }
  function summarizeHealth(data) {
    if (!data || data.status !== "ok" || !data.runtime ||
        !data.execution || data.execution.real_submit_allowed !== false) {
      return {state:"UNKNOWN",text:"取得証拠: Collector 未確認 ／ Watcher 未確認 ／ Gateway 未確認 ／ BRAIN 未検証 ｜ 実注文禁止"};
    }
    const r=data.runtime;
    const collector=statusLabel(r.collector_publication_state);
    const watcher=statusLabel(r.watcher_publication_state);
    const brain="未検証（独立した観測証拠なし）";
    return {state:"PUBLICATION_ONLY",text:
      "取得証拠: Collector "+collector+" ／ Watcher "+watcher+
      " ／ Gateway 応答あり ／ BRAIN "+brain+
      " ｜ 固定分析は過去データ・実注文禁止"};
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports={statusLabel,summarizeHealth};
  }
  if (typeof document === "undefined" || typeof root.fetch !== "function") return;
  const panel=document.getElementById("v10-publication-panel");
  if (!panel) return;
  let stopped=false;
  let requestInProgress=false;
  function show(summary) {
    if (stopped) return;
    panel.dataset.publication=summary.state;
    panel.textContent=summary.text;
  }
  async function refresh() {
    if (stopped || requestInProgress) return;
    requestInProgress=true;
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),2500);
    try {
      const response=await root.fetch("/health?publication="+Date.now(),
        {cache:"no-store",signal:controller.signal});
      if (!response.ok) throw new Error("HEALTH_UNAVAILABLE");
      show(summarizeHealth(await response.json()));
    } catch (_) {
      show(summarizeHealth(null));
    } finally {
      clearTimeout(timeout);
      requestInProgress=false;
    }
  }
  refresh();
  const interval=setInterval(refresh,15000);
  root.addEventListener("pagehide",()=>{
    stopped=true;
    clearInterval(interval);
    show(summarizeHealth(null));
  });
})(typeof window === "undefined" ? {} : window);
