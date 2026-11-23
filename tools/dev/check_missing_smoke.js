// v10.15.0: the real page against a real running server, in a headless DOM (jsdom): Missing-clip board, Bulletin smoke test, and the on / off switches an admin flips on the page.
// usage: node check_missing_smoke.js <port> <admin email> <admin password> <editor email> <editor password>
const { JSDOM, VirtualConsole } = require("jsdom");
const [port, aEmail, aPass, eEmail, ePass] = process.argv.slice(2), base = "http://127.0.0.1:" + port + "/", sleep = ms => new Promise(r => setTimeout(r, ms));
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
const login = async (email, password) => { const r = await fetch(base + "api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) }); return r.headers.get("set-cookie").split(";")[0]; };
(async () => {
  const [ac, ec] = [await login(aEmail, aPass), await login(eEmail, ePass)], html = await (await fetch(base, { headers: { Cookie: ac } })).text();
  const open = (cookie, store = {}) => { const vc = new VirtualConsole(); vc.on("jsdomError", e => { console.log("PAGE ERROR:", String(e.message).slice(0, 300)); fails++; });
    return new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, url: base, virtualConsole: vc, beforeParse(w) {
      w.fetch = (u, o = {}) => fetch(new URL(u, base), { ...o, headers: { ...(o.headers || {}), Cookie: cookie } });
      w.Response = Response; w.Headers = Headers; w.Request = Request; w.matchMedia = q => ({ matches: /min-width/.test(q), media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
      w.HTMLElement.prototype.scrollIntoView = function () {}; w.scrollTo = () => {}; for (const [k, v] of Object.entries(store)) w.localStorage.setItem(k, v); } }); };
  let dom = open(ac), w = dom.window, d = w.document; await sleep(2200);
  const $ = s => d.querySelector(s), $$ = s => [...d.querySelectorAll(s)], hid = s => $(s).classList.contains("hide"), vis = s => $(s).style.display !== "none";
  const click = async (s, ms = 900) => { $(s).click(); await sleep(ms); };
  const set = async (s, v) => { $(s).value = v; $(s).dispatchEvent(new w.Event("change")); await sleep(1300); };

  // ---- menu + badge
  ok(vis("#navmiss") && vis("#navsmoke"), "both menu items are in the left menu while the features are on");
  ok($("#missn").style.display !== "none" && $("#missn").textContent === "2" && $("#missn").classList.contains("red"), "the Missing item carries a red badge: 2 stories without a clip in a bulletin that starts soon (badge says " + $("#missn").textContent + ")");

  // ---- Missing-clip board
  await click("#navmiss");
  ok(hid("#tab-rundown") && !hid("#missbox") && $("#navmiss").classList.contains("on") && w.localStorage.getItem("autoid_tab") === "missing", "the Missing tab opens on its own and is remembered");
  let cards = $$("#misslist .miss-bul"); ok(cards.length === 2, "two bulletins have stories without a clip: " + cards.length);
  ok(cards[0].classList.contains("red") && /Soon/.test(cards[0].textContent) && /^starts in 1[12] min \d\d s$/.test(cards[0].querySelector(".miss-cd").textContent), "the bulletin 12 minutes away is red with a ticking countdown: " + cards[0].querySelector(".miss-cd").textContent);
  ok(!cards[1].classList.contains("red") && /starts in 1 h 5\d min$/.test(cards[1].querySelector(".miss-cd").textContent), "the bulletin 2 hours away is not red: " + cards[1].querySelector(".miss-cd").textContent);
  ok(cards[0].querySelectorAll(".miss-row").length === 2 && !/Story A/.test(cards[0].textContent) && /Story B/.test(cards[0].textContent), "only the stories without a clip are listed (the attached one is not)");
  const t1 = cards[0].querySelector(".miss-cd").textContent; await sleep(2200); ok(cards[0].querySelector(".miss-cd").textContent !== t1, "the countdown ticks by itself, without a reload (" + t1 + " -> " + cards[0].querySelector(".miss-cd").textContent + ")");
  const kept = cards[0]; await sleep(5500); ok($$("#misslist .miss-bul")[0] === kept, "a refresh with the same data does not rebuild the board (same DOM node kept)");
  ok(/in the red/.test($("#missum").textContent) && /Soon|stor/.test($("#missum").textContent), "the summary counts the red ones: " + $("#missum").textContent);
  const addb = cards[0].querySelector(".miss-row .addb"); ok(!!addb && !addb.disabled && /Add media/.test(addb.textContent), "Add media is on every row, enabled");
  addb.click(); await sleep(1200); const dlg = $(".addm [role=dialog]"); ok(!!dlg && /Add media/.test(dlg.textContent) && /Story B/.test(dlg.textContent), "one click opens the Add media dialog for that story");
  [...dlg.querySelectorAll("button")].find(b => b.textContent === "Cancel").click(); await sleep(200); ok(!$(".addm"), "Cancel closes it");
  $("#missaired").checked = true; $("#missaired").dispatchEvent(new w.Event("change")); await sleep(1200); ok($$("#misslist .miss-bul").length === 3 && /aired/.test($$("#misslist .miss-cd")[0].textContent) && !$$("#misslist .miss-bul")[0].classList.contains("red"), "'also show bulletins that have already aired' adds one, shown as aired and never red");
  $("#missaired").checked = false; $("#missaired").dispatchEvent(new w.Event("change")); await sleep(1000);

  // ---- Bulletin smoke test
  await click('[data-tab="smoke"]');
  ok(hid("#missbox") && !hid("#smokebox") && $$("#smokesel option").length === 3, "the Smoke test tab lists the day's bulletins: " + $$("#smokesel option").map(o => o.textContent.replace(/\s+/g, " ")).join(" | "));
  ok(/Soon/.test($("#smokesel").selectedOptions[0].textContent), "the next bulletin to start is preselected");
  await click("#smokego", 1500);
  ok(/2 of 3 stories have no clip attached/.test($(".smk-verdict").textContent) && $(".smk-verdict").classList.contains("bad"), "Quick test: red verdict: " + $(".smk-verdict").textContent);
  const fills = $$(".smk-fill"), nums = $$(".smk-n").map(x => x.textContent); ok(fills.length === 2 && fills[0].style.width === "100%" && fills[1].style.width === "33%" && nums.join() === "3,1", "horizontal bar graph: total 3 (full bar) and attached 1 (a third): " + fills.map(f => f.style.width) + " / " + nums);
  ok($$("#smokeres .miss-row").length === 2 && $$("#smokeres .miss-row .addb").every(b => !b.disabled), "the 2 stories without a clip are listed, each with Add media");
  $("#smokesel").value = $$("#smokesel option").find(o => /Later/.test(o.textContent)).value; await click("#smokego", 1500);
  ok(/2 of 2/.test($(".smk-verdict").textContent) && $$(".smk-fill")[1].style.width === "0%", "another bulletin: 2 of 2 missing, attached bar empty");
  ok(w.localStorage.getItem("autoid_smoke") !== null, "the chosen bulletin is remembered");

  // ---- the switches (admin) and an editor's page following them
  const ed = open(ec, { autoid_tab: "smoke" }); await sleep(2200); const E = s => ed.window.document.querySelector(s);
  ok(E("#navsmoke").style.display !== "none" && !E("#smokebox").classList.contains("hide") && E("#tab-rundown").classList.contains("hide"), "an editor's remembered Smoke test tab opens on the Smoke test");
  ok(E("#navmiss").style.display !== "none" && E("#navsmoke").style.display !== "none" && E("#navus").style.display === "none", "the editor has Missing and Smoke test, no Users tab, so no switches");
  await click('[data-tab="users"]');
  ok(!hid("#adminbox") && $("#fmiss").checked && $("#fsmoke").checked && $("#fmin").value === "20" && !$("#fmin").disabled, "Users > Features shows both switches on and the limit 20");
  $("#fmiss").click(); await sleep(1500);
  ok(!$("#fmiss").checked && !vis("#navmiss") && $("#fmin").disabled && vis("#navsmoke"), "the admin switches the board off: its menu item goes, the smoke test stays");
  ok(/Saved/.test($("#toasts").textContent), "a toast says it was saved");
  await sleep(6000); ok(E("#navmiss").style.display === "none" && E("#navsmoke").style.display !== "none", "the editor's page follows within a few seconds, with no reload");
  $("#fsmoke").click(); await sleep(1500); await sleep(6000);
  ok(E("#smokebox").classList.contains("hide") && E("#navsmoke").style.display === "none" && !E("#tab-rundown").classList.contains("hide"), "switching the smoke test off while the editor has it open sends the editor back to the Rundown");
  $("#fmiss").click(); await sleep(1500); await set("#fmin", "150"); ok(vis("#navmiss") && $("#fmin").value === "150", "switched on again, the limit set to 150 minutes");
  await click('[data-tab="missing"]', 1500); cards = $$("#misslist .miss-bul"); ok(cards.length === 2 && cards.every(c => c.classList.contains("red")) && $("#missmin").textContent === "150", "with 150 minutes the bulletin 2 hours away turns red too");
  await click('[data-tab="users"]'); await set("#fmin", "abc"); ok(/whole number/.test($("#toasts").textContent) && $("#fmin").value === "150", "a bad limit is refused with a message and the old value stays");
  dom.window.close(); ed.window.close();
  dom = open(ac, { autoid_tab: "smoke" }); w = dom.window; d = w.document; await sleep(2200);
  ok(!hid("#tab-rundown") && hid("#smokebox") && !vis("#navsmoke"), "a remembered tab of a switched-off feature falls back to the Rundown");
  console.log(fails ? "FAILED: " + fails : "ALL CHECKS PASSED"); process.exit(fails ? 1 : 0);
})().catch(e => { console.log("CRASH", e); process.exit(1); });
