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
  if (!page) throw new Error("page not found");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pending = new Map();
  let id = 1;
  ws.addEventListener("message", (event) => {
    const m = JSON.parse(event.data);
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
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Page.navigate", { url: "https://sunway66.github.io/sunway66/" });
  await new Promise((resolve) => setTimeout(resolve, 9000));
  const result = await send("Runtime.evaluate", {
    expression: `(async () => {
      const r = await fetch("./data.json?t=" + Date.now(), { cache: "no-store" });
      const d = await r.json();
      return JSON.stringify({
        demo: d.demo,
        dates: d.dates.length,
        csiKeys: d.csi300 ? Object.keys(d.csi300) : null,
        peTtm: d.csi300?.pe_ttm?.filter((v) => v != null).length || 0,
        bond: d.csi300?.bond_yield?.filter((v) => v != null).length || 0,
        riskCount: d.csi300?.risk_premium?.filter((v) => v != null).length || 0,
        indexCount: d.csi300?.index_close?.filter((v) => v != null).length || 0,
        peSample: d.csi300?.pe_ttm?.slice(-3) || null,
        bondSample: d.csi300?.bond_yield?.slice(-3) || null,
        risk: d.csi300?.risk_premium?.slice(-3) || null,
        index: d.csi300?.index_close?.slice(-3) || null,
        formula: d.csi300?.formula || null
      });
    })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  console.log(result.result.value);
  ws.close();
})().catch((e) => { console.error(e); process.exit(1); });
