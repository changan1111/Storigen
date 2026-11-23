// v10.10.0: the real page, against a real running server (with a fake Blaze and the poller running), in a headless DOM (jsdom): the Support tab, Add media, Delete media, the Yes / No dialogs and the notification.
// usage: node check_support_menu.js <port> <email> <password>
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
    w.HTMLElement.prototype.scrollIntoView = function () {}; w.scrollTo = () => {}; w.confirm = () => true; w.alert = m => console.log("ALERT:", m); } });
  const w = dom.window, d = w.document, $ = s => d.querySelector(s), all = s => [...d.querySelectorAll(s)], hid = s => $(s).classList.contains("hide"), txt = s => ($(s) || {}).textContent || "";
  const until = async (f, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) { if (f()) return true; await sleep(200); } return false; };
  const pickBullStory = async (sel) => { const bs = $("#supform select"); bs.value = bs.options[1].value; bs.dispatchEvent(new w.Event("change")); await until(() => all("#supform .spi").length > 0);
    all("#supform .spi").find(b => b.textContent.includes(sel)).click(); await sleep(300); };
  await sleep(2000);
  const nav = $("#navsup"); ok(!!nav && nav.style.display !== "none" && !!nav.querySelector("svg.ic") && txt("#navsup .lb") === "Support", "the side menu has a Support item with an icon");
  nav.click(); await sleep(500);
  ok(!hid("#supbox") && hid("#tab-rundown"), "the Support tab opens on its own");
  ok(/For exceptions only\./.test(txt(".sup-note")) && /only when something really needs fixing/.test(txt(".sup-note")), "the note says it is not recommended unless really needed: " + txt(".sup-note"));
  ok(txt("#supadd") === "Add media" && txt("#supdel") === "Delete media", "the two buttons: Add media, Delete media");
  // ---- Add media: pick a clip from the list
  $("#supadd").click(); await until(() => $("#supform select"));
  ok(all("#supform select option").length >= 2 && /Bulletin/.test(txt("#supform")), "step 1: the bulletin list is filled");
  await pickBullStory("AUTO ID 05"); await until(() => $("#supform .spk:nth-of-type(2), #supform .st"));
  await until(() => all("#supform .spk").length === 2);
  ok(all("#supform .spk").length === 2 && !!$("#supform .spk input[type=search]"), "step 3: a clip drop-down with a search box on top");
  ok(all("#supform .spk")[1].querySelectorAll(".spi").length === 1, "the list holds the file the log found");
  const si = all("#supform .spk")[1].querySelector("input"); si.value = "zzzz"; si.dispatchEvent(new w.Event("input")); ok(/No match/.test(all("#supform .spk")[1].textContent), "the search narrows the list");
  si.value = ""; si.dispatchEvent(new w.Event("input")); all("#supform .spk")[1].querySelector(".spi").click(); await sleep(200);
  ok(/Type the correct name and queue it/.test(txt("#supform")), "a 'not in the list? type the correct name and queue it' box is there");
  const goBtn = all("#supform button").find(b => b.textContent === "Attach clip"); ok(!!goBtn, "the button says Attach clip"); goBtn.click(); await sleep(300);
  ok(/Attach this clip to the story\?/.test(txt("body")) && all("button").some(b => b.textContent === "Yes, attach") && all("button").some(b => b.textContent === "No"), "a Yes / No question comes first");
  all("button").find(b => b.textContent === "No").click(); await sleep(300); ok((await (await fetch(base + "api/support/jobs", { headers: { Cookie: cookie } })).json()).jobs.length === 0, "No: nothing is queued");
  goBtn.click(); await sleep(300); all("button").find(b => b.textContent === "Yes, attach").click();
  ok(await until(() => all("#toasts .toast.ok").some(t => /Media added/.test(t.textContent))), "when it is attached, a notification appears");
  ok(await until(() => /Done/.test(txt("#supq"))) && /Add media/.test(txt("#supq")), "the queue table shows it as Done");
  // ---- typed name is queued
  $("#supadd").click(); await until(() => $("#supform select")); await pickBullStory("SECOND STORY"); await until(() => all("#supform .spk").length === 2);
  const nm = $("#supform input[type=text]"); nm.value = "hello world"; nm.dispatchEvent(new w.Event("input")); ok(all("#supform button").some(b => b.textContent === "Queue it"), "typing a name turns the button into Queue it");
  nm.value = "221126_NOT_THERE_YET"; nm.dispatchEvent(new w.Event("input")); all("#supform button").find(b => b.textContent === "Queue it").click(); await sleep(300);
  ok(/Queue this clip\?/.test(txt("body")), "queueing asks Yes / No too"); all("button").find(b => b.textContent === "Yes, queue it").click();
  ok(await until(() => /Queued/.test(txt("#supq")) && /221126_NOT_THERE_YET/.test(txt("#supq"))), "the queued name shows in the queue, waiting"); ok(txt("#supn") === "1" && $("#supn").style.display !== "none", "the menu icon shows 1 open request");
  const cancel = all("#supq button").find(b => b.textContent === "Cancel"); ok(!!cancel, "a queued request has a Cancel button"); cancel.click(); await sleep(300); all("button").find(b => b.textContent === "Yes, cancel").click();
  ok(await until(() => /Cancelled/.test(txt("#supq"))), "cancelled");
  // ---- Delete media
  $("#supdel").click(); await until(() => $("#supform select")); await pickBullStory("AUTO ID 05");
  ok(await until(() => all("#supform .supclip").length === 1), "the clips of the story are read from Blaze and listed"); all("#supform .supclip input")[0].click(); await sleep(200);
  const del = all("#supform button").find(b => b.textContent === "Delete media"); ok(!!del && !del.disabled, "Delete media is enabled once a clip is chosen"); del.click(); await sleep(300);
  ok(/Delete this clip from the story\?/.test(txt("body")) && /The file itself stays in Nitro/.test(txt("body")) && all("button").some(b => b.textContent === "Yes, delete"), "the confirm says the file stays in Nitro, with Yes / No");
  all("button").find(b => b.textContent === "No").click(); await sleep(300); ok(!(await (await fetch(base + "api/support/jobs", { headers: { Cookie: cookie } })).json()).jobs.some(j => j.kind === "REMOVE"), "No: nothing is deleted");
  del.click(); await sleep(300); all("button").find(b => b.textContent === "Yes, delete").click();
  ok(await until(() => all("#toasts .toast.ok").some(t => /Media deleted/.test(t.textContent))), "after the delete, a notification appears");
  console.log(fails ? "FAILED: " + fails : "ALL CHECKS PASSED"); process.exit(fails ? 1 : 0);
})();
