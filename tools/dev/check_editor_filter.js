// v10.9.5: the real page, against a real running server, in a headless DOM (jsdom): the editor-name picker and the top search.
// usage: node check_editor_filter.js <port> <email> <password>
const { JSDOM, VirtualConsole } = require("jsdom");
const [port, email, pass] = process.argv.slice(2), base = "http://127.0.0.1:" + port + "/", sleep = ms => new Promise(r => setTimeout(r, ms));
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const lr = await fetch(base + "api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: pass }) });
  const cookie = lr.headers.get("set-cookie").split(";")[0], html = await (await fetch(base, { headers: { Cookie: cookie } })).text();
  const vc = new VirtualConsole(); vc.on("jsdomError", e => console.log("PAGE ERROR:", String(e.message).slice(0, 200)));
  const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, url: base, virtualConsole: vc, beforeParse(w) {
    w.fetch = (u, o = {}) => fetch(new URL(u, base), { ...o, headers: { ...(o.headers || {}), Cookie: cookie } });
    w.Response = Response; w.Headers = Headers; w.Request = Request; w.matchMedia = q => ({ matches: /min-width/.test(q), media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
    w.HTMLElement.prototype.scrollIntoView = function () {}; } });
  const w = dom.window, d = w.document, $ = s => d.querySelector(s), rows = () => [...d.querySelectorAll("#list .sr")].map(r => r.querySelector(".tt").textContent);
  await sleep(2200);
  const f = $("#editf"); ok(!!f && /All editors/.test(f.querySelector("summary").textContent), "the editor picker is on the page: " + (f && f.querySelector("summary").textContent));
  const labels = () => [...f.querySelectorAll(".upl label")].map(l => l.textContent.trim());
  ok(labels().length === 2 && labels()[0] === "VD KARTHIK (1)" && labels()[1] === "VD VIGNESH (2)", "it lists every editor name of the day with the number of stories: " + labels().join(" | "));
  ok(rows().length === 4, "no filter: all " + rows().length + " stories");
  const tick = n => { const c = [...f.querySelectorAll(".upl input")].find(i => i.value === n); c.checked = !c.checked; c.dispatchEvent(new w.Event("change")); };
  tick("VD VIGNESH"); await sleep(1200);
  ok(rows().length === 2 && f.querySelector("summary").textContent === "VD VIGNESH" && w.localStorage.getItem("autoid_editor") === "VD VIGNESH", "ticking an editor shows only their stories (" + rows().join(", ") + "), the summary names them and the choice is remembered");
  tick("VD KARTHIK"); await sleep(1200);
  ok(rows().length === 3 && /VD VIGNESH \+1|VD KARTHIK/.test(f.querySelector("summary").textContent) && w.localStorage.getItem("autoid_editor").split(",").length === 2, "two editors ticked: the stories of either (" + rows().length + ")");
  f.querySelector(".ux").click(); await sleep(1200);
  ok(rows().length === 4 && f.querySelector("summary").textContent === "All editors" && !w.localStorage.getItem("autoid_editor"), "Clear: all stories again");
  const q = $("#q"); ok(/editor/.test(q.placeholder), "the top search says it finds editors: " + q.placeholder);
  q.value = "karthik"; q.dispatchEvent(new w.Event("input")); await sleep(1500);
  ok(rows().length === 1 && rows()[0] === "story four", "typing an editor name in the top search finds the story: " + rows().join(", "));
  q.value = ""; q.dispatchEvent(new w.Event("input")); await sleep(1200);
  ok(rows().length === 4, "search cleared: all stories again");
  const up = f.querySelector(".ups"); up.value = "zzz"; up.dispatchEvent(new w.Event("input")); ok(/No match/.test(f.querySelector(".upl").textContent), "typing in the picker's own box narrows its list");
  console.log(fails ? "FAILED: " + fails : "ALL CHECKS PASSED"); process.exit(fails ? 1 : 0);
})().catch(e => { console.log("CRASH", e); process.exit(2); });
