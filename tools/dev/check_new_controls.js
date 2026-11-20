// v10.9.4: the real page, against a real running server, in a headless DOM (jsdom): sort headers, the Removed filter and the hide switch,
// the "updated" stamp, the history / database line, the lost-connection state. usage: node check_new_controls.js <port> <email> <password>
const { JSDOM, VirtualConsole } = require("jsdom");
const [port, email, pass] = process.argv.slice(2), base = "http://127.0.0.1:" + port + "/", TICK = 400, sleep = ms => new Promise(r => setTimeout(r, ms));
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const lr = await fetch(base + "api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: pass }) });
  const cookie = lr.headers.get("set-cookie").split(";")[0], html = await (await fetch(base, { headers: { Cookie: cookie } })).text();
  let broken = false;
  const open = (store = {}) => {
    const vc = new VirtualConsole(); vc.on("jsdomError", e => console.log("PAGE ERROR:", String(e.message).slice(0, 200)));
    return new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, url: base, virtualConsole: vc, beforeParse(w) {
      const si = w.setInterval.bind(w); w.setInterval = (f, ms, ...a) => si(f, ms === 5000 ? TICK : ms, ...a);
      w.fetch = (u, o = {}) => broken ? Promise.reject(new TypeError("network down")) : fetch(new URL(u, base), { ...o, headers: { ...(o.headers || {}), Cookie: cookie } });
      w.Response = Response; w.Headers = Headers; w.Request = Request; w.matchMedia = q => ({ matches: /min-width/.test(q), media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
      w.HTMLElement.prototype.scrollIntoView = function () {}; for (const [k, v] of Object.entries(store)) w.localStorage.setItem(k, v); } });
  };
  let dom = open(), w = dom.window, d = w.document; await sleep(2200);
  const $ = s => d.querySelector(s), rows = () => [...d.querySelectorAll("#list .sr")], titles = () => rows().map(r => r.querySelector(".tt").textContent), nums = () => rows().map(r => r.querySelector(".n").textContent);
  const hdr = k => $('.sh0 .shb[data-k="' + k + '"]'), cmp = (a, b) => a.toLowerCase() < b.toLowerCase() ? -1 : a.toLowerCase() > b.toLowerCase() ? 1 : 0;
  ok(rows().length >= 5, "the page lists " + rows().length + " stories");
  ok(/^updated \d\d:\d\d$/.test($("#upd").textContent), "the page shows when it last got data: " + $("#upd").textContent);
  ok(/history kept 7 days/.test($("#keepn").textContent) && /^\d{4}-\d\d-\d\d$/.test($("#day").min), "next to the date: " + $("#keepn").textContent + " (the date picker starts at " + $("#day").min + ")");
  ok(/Database [\d.]+ MB · history kept 7 days \(from \d{4}-\d\d-\d\d\), cleaned daily at 03:30 · not cleaned yet/.test($("#dbinfo").textContent) && !!$("#dbinfo button"), "the footer: " + $("#dbinfo").textContent.trim());
  // sorting
  hdr("title").click(); await sleep(900);
  let t = titles(); ok(t.length >= 5 && JSON.stringify(t) === JSON.stringify([...t].sort(cmp)) && hdr("title").getAttribute("aria-sort") === "ascending" && /▲/.test(hdr("title").textContent), "Story Title: ascending (" + t.slice(0, 3).join(" | ") + " ...)");
  ok(w.localStorage.getItem("autoid_sort") === "title:asc" && !$("#srt").classList.contains("hide") && /Sorted by story title/.test($("#srt").textContent), "...remembered in the browser, with a 'Sorted by' reset button: " + $("#srt").textContent);
  hdr("title").click(); await sleep(900);
  t = titles(); ok(JSON.stringify(t) === JSON.stringify([...t].sort(cmp).reverse()) && hdr("title").getAttribute("aria-sort") === "descending" && /▼/.test(hdr("title").textContent) && w.localStorage.getItem("autoid_sort") === "title:desc", "a second click: descending");
  hdr("title").click(); await sleep(900);
  ok(hdr("title").getAttribute("aria-sort") === "none" && $("#srt").classList.contains("hide") && !w.localStorage.getItem("autoid_sort"), "a third click: back to the default order, the reset button is gone");
  hdr("row").click(); await sleep(900); const n1 = nums().filter(x => x !== "").map(Number);
  ok(n1.length >= 4 && n1.every((x, i) => i === 0 || n1[i - 1] <= x), "#: ascending " + n1.slice(0, 6).join(","));
  hdr("row").click(); await sleep(900); const n2 = nums().filter(x => x !== "").map(Number);
  ok(n2.length === n1.length && n2.every((x, i) => i === 0 || n2[i - 1] >= x), "#: descending " + n2.slice(0, 6).join(","));
  hdr("status").click(); await sleep(900); const tg = rows().map(r => r.querySelector(".tag").textContent);
  ok(tg[0] === "Needs Desk" && tg[tg.length - 1] === "Attached", "Status: the clips that need the desk come first (" + tg[0] + " ... " + tg[tg.length - 1] + ")");
  $("#srt").click(); await sleep(900); ok(hdr("status").getAttribute("aria-sort") === "none", "the reset button clears the sort");
  // removed stories
  const opt = [...$("#fsel").options].find(o => o.value === "removed"); ok(!!opt && /^Removed \(4\)$/.test(opt.textContent), "the filter list has: " + (opt && opt.textContent));
  const gone = () => rows().filter(r => r.classList.contains("gone")).length;
  const all = rows().length, g0 = gone(); ok(g0 === 4, "struck-out stories are in the full list (" + g0 + ")");
  const hc = $("#hrm"); hc.checked = true; hc.dispatchEvent(new w.Event("change")); await sleep(900);
  ok(gone() === 2 && rows().length === all - 2 && w.localStorage.getItem("autoid_hide_rm") === "1", "Hide removed: the two that need nothing go, the two still needing the desk stay (" + rows().length + " of " + all + ")");
  $("#fsel").value = "removed"; $("#fsel").dispatchEvent(new w.Event("change")); await sleep(900);
  ok(rows().length === 4 && gone() === 4 && hc.disabled, "Removed filter: only the 4 struck-out stories, and the switch steps aside");
  $("#fsel").value = "all"; $("#fsel").dispatchEvent(new w.Event("change")); hc.checked = false; hc.dispatchEvent(new w.Event("change")); await sleep(900);
  ok(!hc.disabled && rows().length === all && w.localStorage.getItem("autoid_hide_rm") === "0", "switch off again: everything is back");
  // lost connection and recovery
  broken = true; await sleep(TICK * 3); ok($("#sub").classList.contains("stale") && /Cannot reach the service/.test($("#sub").textContent) && /Last updated \d\d:\d\d:\d\d/.test($("#sub").textContent), "connection lost: " + $("#sub").textContent);
  broken = false; await sleep(TICK * 4); ok(!$("#sub").classList.contains("stale") && !/Cannot reach/.test($("#sub").textContent), "...and it clears by itself when the server answers again");
  w.close();
  // remembered across a reload / a new login: a descending title sort and hide-removed, set before the page loads
  dom = open({ autoid_sort: "title:desc", autoid_hide_rm: "1" }); w = dom.window; d = dom.window.document; await sleep(2200);
  const t2 = [...d.querySelectorAll("#list .sr .tt")].map(x => x.textContent);
  ok(t2.length >= 5 && JSON.stringify(t2) === JSON.stringify([...t2].sort(cmp).reverse()) && d.querySelector("#hrm").checked && /▼/.test(d.querySelector('.sh0 .shb[data-k="title"]').textContent), "a new page load comes up with the remembered sort and switch");
  w.close(); console.log(fails ? fails + " CHECK(S) FAILED" : "ALL CHECKS PASSED"); process.exit(fails ? 1 : 0);
})().catch(e => { console.log("ERROR", e); process.exit(2); });
