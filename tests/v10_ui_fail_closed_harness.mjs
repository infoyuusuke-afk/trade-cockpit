// P0-V10-ROW-GATE-OPERABILITY-20261019: the dashboard's own fail-closed code
// on synthetic Gateway/Collector responses.
//
// Runs the unmodified fetchMs2 / loadMs2Live decision lines from index.html
// (extracted as text, not re-implemented) with card_system.js livePriceBlocked
// and a fake fetch. Input on stdin: a JSON list of cases
//   {name, bridge_status, bridge_body, health}
// Output on stdout: one JSON object {name: {stale, blocked, xs_len, health_text}}.
// Synthetic data only; nothing is fetched from the network.
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// A Windows checkout may carry CRLF line endings.
const html = readFileSync(path.join(root, "index.html"), "utf8").replace(/\r\n/g, "\n");
const { livePriceBlocked } = await import(pathToFileURL(path.join(root, "card_system.js")).href);

function slice(startMarker, endMarker) {
  const start = html.indexOf(startMarker);
  if (start < 0) throw new Error("UI_SOURCE_MARKER_MISSING " + startMarker);
  const end = html.indexOf(endMarker, start);
  if (end < 0) throw new Error("UI_SOURCE_MARKER_MISSING " + endMarker);
  return html.slice(start, end + endMarker.length);
}

const fetchJsonSrc = slice(" const fetchJson=async(", "};\n");
const fetchMs2Src = slice(" const fetchMs2=async()=>{", "\n };\n");
const controllerSrc = slice("   const controllerForcesFailClosed=", ";\n");
const staleSrc = slice("   const parsed=new Date(", ";\n");
const healthTextSrc = slice(" health.textContent=stale?", ";");
const xsSrc = slice("   const xs=!stale&&", ";\n");

const body = [
  fetchJsonSrc,
  fetchMs2Src,
  "return (async()=>{",
  " const d=await fetchMs2();",
  controllerSrc,
  staleSrc,
  " const healthText=" + healthTextSrc.replace(" health.textContent=", ""),
  xsSrc,
  " return {stale, blocked, xs_len: xs.length, health_text: healthText};",
  "})();",
].join("\n");
// eslint-disable-next-line no-new-func
const run = new Function("window", "fetch", "controllerHealth", body);

function response(status, text) {
  return { ok: status >= 200 && status < 300, status, json: async () => JSON.parse(text) };
}

const cases = JSON.parse(readFileSync(0, "utf8"));
const out = {};
for (const item of cases) {
  const fakeFetch = async (url) => {
    if (String(url).startsWith("http://127.0.0.1:28580/live_ms2.json")) {
      return response(item.bridge_status, item.bridge_body);
    }
    throw new Error("NO_NETWORK_IN_TEST " + url);
  };
  try {
    out[item.name] = await run({ livePriceBlocked }, fakeFetch, item.health ?? null);
  } catch (error) {
    out[item.name] = { error: String(error) };
  }
}
process.stdout.write(JSON.stringify(out));
