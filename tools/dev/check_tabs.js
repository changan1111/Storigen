// v10.9.5: the real page, against a real running server, in a headless DOM (jsdom): the tabs (Rundown, Ready feed, Recent activity with its 1 / 2 / 4 hour filter, Users).
// usage: node check_tabs.js <port> <email> <password> <admin|editor>
const { JSDOM, VirtualConsole } = require("jsdom");
const [port, email, pass, kind] = process.argv.slice(2), base = "http://127.0.0.1:" + port + "/", sleep = ms => new Promise(r => setTimeout(r, ms));
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const lr = await fetch(base + "api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: pass }) });
  const cookie = lr.headers.get("set-cookie").split(";")[0], html = await (await fetch(base, { headers: { Cookie: cookie } })).text();
  const open = (store = {}) => { const vc = new VirtualConsole(); vc.on("jsdomError", e => console.log("PAGE ERROR:", String(e.message).slice(0, 200)));
    return new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, url: base, virtualConsole: vc, beforeParse(w) {
      w.fetch = (u, o = {}) => fetch(new URL(u, base), { ...o, headers: { ...(o.headers || {}), Cookie: cookie } });
      w.Response = Response; w.Headers = Headers; w.Request = Request; w.matchMedia = q => ({ matches: /min-width/.test(q), media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
      w.HTMLElement.prototype.scrollIntoView = function () {}; w.scrollTo = () => {}; for (const [k, v] of Object.entries(store)) w.localStorage.setItem(k, v); } }); };
  let dom = open(), w = dom.window, d = w.document; await sleep(2000);
  const $ = s => d.querySelector(s), hid = s => $(s).classList.contains("hide"), shown = s => w.getComputedStyle($(s)).display !== "none", tabs = () => [...d.querySelectorAll("#nav [data-tab]")].filter(b => b.style.display !== "none").map(b => b.dataset.tab);
  const click = async s => { $(s).click(); await sleep(900); };
  ok(!hid("#tab-rundown") && hid("#feed") && hid("#deskbox") && hid("#adminbox") && $('#nav [data-tab="rundown"]').classList.contains("on"), "it opens on the Rundown tab alone");
  ok(!!$("#list .sr") && !d.querySelector("#tab-rundown #feedbtn"), "the rundown is there, and the Ready feed button is a tab in the header, no longer in the toolbar");
  if (kind === "editor") {
    ok(!tabs().includes("users") && tabs().includes("feed"), "an editor sees the tabs: " + tabs().join(", ") + " (no Users tab: that is for admins)");
    w.localStorage.setItem("autoid_tab", "users"); dom.window.close(); dom = open({ autoid_tab: "users" }); w = dom.window; d = w.document; await sleep(2000);
    ok(!hid("#tab-rundown") && hid("#adminbox"), "a remembered Users tab falls back to the Rundown for someone who may not use it");
    console.log(fails ? "FAILED: " + fails : "ALL CHECKS PASSED"); process.exit(fails ? 1 : 0);
  }
  ok(tabs().join() === "rundown,feed,support,missing,smoke,insights,activity,users", "an admin sees the tabs: " + tabs().join(", "));
  // Recent activity
  await click('[data-tab="activity"]');
  ok(hid("#tab-rundown") && !hid("#deskbox") && hid("#adminbox") && $('#nav [data-tab="activity"]').classList.contains("on") && w.localStorage.getItem("autoid_tab") === "activity", "Recent activity is a tab of its own, remembered in the browser");
  const acts = () => [...d.querySelectorAll("#ev tr td:nth-child(3)")].map(x => x.textContent), opts = [...$("#evh").options].map(o => o.value + ":" + o.textContent);
  ok(opts.join() === "1:1 hour,2:2 hours,4:4 hours" && $("#evh").value === "1", "the time filter offers 1 / 2 / 4 hours, 1 hour first: " + opts.join(" | "));
  ok(acts().includes("t_30min") && !acts().includes("t_90min") && !acts().includes("t_3h") && !acts().includes("t_6h"), "last 1 hour: " + acts().filter(a => /^t_/.test(a)).join(", "));
  $("#evh").value = "2"; $("#evh").dispatchEvent(new w.Event("change")); await sleep(900);
  ok(acts().includes("t_30min") && acts().includes("t_90min") && !acts().includes("t_3h") && w.localStorage.getItem("autoid_evh") === "2", "last 2 hours adds the 90 minute one: " + acts().filter(a => /^t_/.test(a)).join(", "));
  $("#evh").value = "4"; $("#evh").dispatchEvent(new w.Event("change")); await sleep(900);
  ok(acts().includes("t_3h") && !acts().includes("t_6h") && /event/.test($("#evn").textContent), "last 4 hours adds the 3 hour one, never the 6 hour one: " + $("#evn").textContent);
  // Users
  await click('[data-tab="users"]');
  ok(hid("#tab-rundown") && hid("#deskbox") && !hid("#adminbox") && !!$("#nadd") && !!$("#ne") && [...d.querySelectorAll("#ut tr")].some(r => r.textContent.includes(email)), "Users is a tab of its own: the add-user form and the list (" + d.querySelectorAll("#ut tr").length + " user(s))");
  // Ready feed
  await click("#feedbtn");
  ok(hid("#tab-rundown") && hid("#adminbox") && !hid("#feed") && $("#feed").classList.contains("tab") && $("#feedbtn").classList.contains("on") && !d.body.classList.contains("fd-dock") && !!$("#fq"), "Ready feed is a tab of its own (search, filters and the list inside it)");
  ok(w.getComputedStyle($("#feedx")).display === "none" || $("#feed").classList.contains("tab"), "no close / minimize buttons are needed in the tab");
  await click('[data-tab="rundown"]');
  ok(!hid("#tab-rundown") && hid("#feed"), "back on Rundown: the feed is closed, the stories are shown");
  // remembered across a reload
  dom.window.close(); dom = open({ autoid_tab: "activity", autoid_evh: "2" }); w = dom.window; d = w.document; await sleep(2200);
  ok(!hid("#deskbox") && hid("#tab-rundown") && $("#evh").value === "2" && acts().includes("t_90min"), "after a reload the same tab and the same time window are back");
  console.log(fails ? "FAILED: " + fails : "ALL CHECKS PASSED"); process.exit(fails ? 1 : 0);
})().catch(e => { console.log("CRASH", e); process.exit(2); });
