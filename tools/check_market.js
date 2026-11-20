const http = require("http");
const getJson = (path) => new Promise((resolve, reject) => {
  http.get({ host: "127.0.0.1", port: 9224, path }, (res) => {
    let data = "";
    res.on("data", (c) => (data += c));
    res.on("end", () => resolve(JSON.parse(data)));
  }).on("error", reject);
});
(async () => {
  const targets = await getJson("/json");
  const page = targets.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pending = new Map();
  let id = 1;
  ws.addEventListener("message", (event) => {
    const m = JSON.parse(event.data);
    if (m.method === "Runtime.exceptionThrown") {
      console.error("PAGE EXCEPTION", JSON.stringify(m.params.exceptionDetails));
    }
    if (m.method === "Runtime.consoleAPICalled") {
      const args = (m.params.args || []).map((a) => a.value ?? a.description).join(" ");
      console.error("PAGE CONSOLE", m.params.type, args);
    }
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result);
    }
  });
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const mid = id++; pending.set(mid, { resolve, reject });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await new Promise((r) => setTimeout(r, 6000));
  const result = await send("Runtime.evaluate", {
    expression: `(async () => {
      const r = await fetch("./data.json?t=" + Date.now(), { cache: "no-store" });
      const d = await r.json();
      const market = d.market;
      return JSON.stringify({
        demo: d.demo,
        dates: d.dates.length,
        marketIsNull: market == null,
        marketKeys: market ? Object.keys(market) : null,
        marketDate: market?.date || null,
        marketTotal: market?.total ?? null,
        marketUp: market?.up ?? null,
        marketDown: market?.down ?? null,
        marketDistribution: market?.distribution?.length ?? null,
        marketIsStale: market?.is_stale ?? null,
        domUp: document.querySelector("#upCount")?.textContent,
        domDown: document.querySelector("#downCount")?.textContent,
        domNote: document.querySelector("#marketNote")?.textContent,
        status: document.querySelector("#statusText")?.textContent,
        charts: document.querySelectorAll("canvas").length
      });
    })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  console.log(result.result.value);
  ws.close();
})().catch((e) => { console.error(e); process.exit(1); });
