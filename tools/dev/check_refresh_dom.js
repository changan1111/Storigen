#!/usr/bin/env node
/* Developer check (not needed to run Storigen): proves the dashboard's automatic refresh does not disturb the page.
   It runs the REAL page code (index.html + the sample-data shim) in a headless DOM (jsdom), with the 5 s refresh sped up,
   and checks that
     1. while the data does not change, the refresh makes ZERO changes to the page and keeps the very same elements;
     2. when the data does change, the page still updates and only the changed story's row is rebuilt;
     3. Pause refresh / the P key stop and resume it;
     4. a warning whose number ticks ("last seen 47s ago") is updated in place, not replaced.
     5. the Ready feed (a table): columns, newest first, search, filter, Quick test attach (Yes / No), open the story, a toast for a newly ready clip (once), no changes while open, Esc / F keys.
   Setup, once:  cd tools/dev && npm install jsdom        Run:  python3 tools/make_standalone.py --out /tmp/s.html && node tools/dev/check_refresh_dom.js /tmp/s.html */
const { JSDOM, VirtualConsole } = require("jsdom"); const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8"), TICK = 400, sleep = ms => new Promise(r => setTimeout(r, ms)); let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
function open() {
  const vc = new VirtualConsole(); vc.on("jsdomError", e => console.log("PAGE ERROR:", String(e.message).slice(0, 200)));
  return new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, url: "http://localhost/", virtualConsole: vc, beforeParse(w) {
    const t0 = Date.now(), si = w.setInterval.bind(w); w.Date.now = () => t0;                 // frozen clock: the sample data stamps "N minutes ago" from it
    w.setInterval = (f, ms, ...a) => si(f, ms === 5000 ? TICK : ms, ...a);                    // the page's 5 s refresh runs every 0.4 s here
    w.Response = Response; w.Headers = Headers; w.Request = Request; w.fetch = (...a) => fetch(...a);
    w.matchMedia = q => ({ matches: /min-width/.test(q), media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
    w.HTMLElement.prototype.scrollIntoView = function () {}; } });
}
const where = n => { let e = n.nodeType === 1 ? n : n.parentElement; while (e && !e.id) e = e.parentElement; return e ? "#" + e.id : "(page)"; };
(async () => {
  // 1. nothing changed -> nothing touched
  let dom = open(), w = dom.window, d = w.document; await sleep(1500);
  const rows = () => [...d.querySelectorAll("#list .sr")], txt = s => (d.querySelector(s) || {}).textContent;
  ok(rows().length > 1, "page loaded with " + rows().length + " story rows");
  rows()[2].click(); await sleep(400);
  const keepRow = d.querySelector("#list .sr.sel"), keepBox = d.querySelector("#mid .sbody"), keepBtn = d.querySelector("#detail button"), counts = {}; let total = 0;
  new w.MutationObserver(rs => { for (const r of rs) { const k = where(r.target); counts[k] = (counts[k] || 0) + 1; total++; } }).observe(d.body, { subtree: true, childList: true, attributes: true, characterData: true });
  await sleep(TICK * 8);
  ok(total === 0, "8 refreshes with unchanged data made " + total + " change(s) to the page " + (total ? JSON.stringify(counts) : ""));
  ok(d.querySelector("#list .sr.sel") === keepRow && d.querySelector("#mid .sbody") === keepBox && d.querySelector("#detail button") === keepBtn, "the selected row, the script box and the detail buttons are the very same elements");
  // 2. one story changes -> the page follows, only that row is rebuilt
  const list = await (await w.fetch("/api/clips?page=1&per_page=200&filter=all")).json(), target = list.clips.find(c => c.state !== "ATTACHED");
  const before = new Set(rows()), statsBefore = txt("#stats");
  await w.fetch("/api/clips/" + target.id + "/quickattach", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); await sleep(TICK * 4);
  const fresh = rows().filter(n => !before.has(n));
  ok(txt("#stats") !== statsBefore, "the counters followed the change"); ok(fresh.length <= 1 && rows().length - fresh.length >= 1, "only the changed story's row was rebuilt (" + fresh.length + " new, " + (rows().length - fresh.length) + " kept)");
  // 3. pause / resume / P
  const pb = d.querySelector("#pause"); pb.click(); ok(pb.textContent === "Resume refresh" && txt("#sub").includes("refresh paused"), "Pause refresh: the button says Resume and the header says paused");
  const l2 = await (await w.fetch("/api/clips?page=1&per_page=200&filter=all")).json(), t2 = l2.clips.find(c => c.state !== "ATTACHED"), sp = txt("#stats");
  await w.fetch("/api/clips/" + t2.id + "/quickattach", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); await sleep(TICK * 4);
  ok(txt("#stats") === sp, "while paused the page does not change although the data did"); pb.click(); await sleep(300);
  ok(txt("#stats") !== sp && pb.textContent === "Pause refresh" && txt("#sub").includes("refreshes every 5 s"), "Resume refreshes at once");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "p", bubbles: true })); ok(pb.textContent === "Resume refresh", "the P key pauses");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "P", bubbles: true })); await sleep(300); ok(pb.textContent === "Pause refresh", "the P key resumes"); w.close();
  // 4. a ticking warning is updated in place
  dom = open(); w = dom.window; d = w.document; await sleep(1200); let n = 40; const inner = w.fetch;
  w.fetch = (u, o) => String(u).startsWith("/api/status") ? Promise.resolve(new Response(JSON.stringify({ problems: ["blaze_poll last seen " + (n += 5) + "s ago"] }), { headers: { "Content-Type": "application/json" } })) : inner(u, o);
  await sleep(TICK * 3); const e1 = d.querySelector("#warn .warn"), t1 = e1 && e1.textContent; await sleep(TICK * 4); const e2 = d.querySelector("#warn .warn");
  ok(e1 && e1 === e2 && t1 !== e2.textContent, "a warning whose number ticks stays the same element and keeps updating: [" + t1 + "] -> [" + (e2 && e2.textContent) + "]"); w.close();
  // 5. Ready feed (a table): columns, newest first, search, filter, Quick test attach, open the story, new-arrival toast, no disturbance while open, Esc
  dom = open(); w = dom.window; d = w.document; await sleep(1500); const inner2 = w.fetch; let inject = false, lastFeed = []; const alerts = []; w.alert = m => alerts.push(String(m));
  w.fetch = (u, o) => String(u).startsWith("/api/feed") ? inner2(u, o).then(async r => { const j = await r.json(); if (inject && !(u.includes("q="))) { j.items.unshift({ id: 999, display_id: "X", name_id: "NEW_TEST_CLIP", version: 1, blaze_story_id: "999001", blaze_rundown_id: "nope", story: "Breaking test story", slug: "BT", bulletin: "Test", mos_object_id: "MOS-999", media_name: "BREAKING.mxf", ready_at: new Date().toISOString(), attached_at: null, status: "READY", status_text: "Ready to attach", state: "ON_NITRO", qa_state: null, typed: false, reason: null }); j.counts.ready++; j.counts.all++; j.total++; } if (!u.includes("q=") && !u.includes("status=")) lastFeed = j.items; return new Response(JSON.stringify(j), { headers: { "Content-Type": "application/json" } }); }) : inner2(u, o);
  const q$ = s => d.querySelector(s), badge0 = +q$("#feedn").textContent, cell = (r, k) => { const t = k === 2 && r.children[k].querySelector(".ttl"); return t ? t.textContent : r.children[k].textContent; };
  ok(badge0 > 0 && q$("#feedbtn").classList.contains("hot"), "feed badge shows how many clips are ready to attach (" + badge0 + ")");
  q$("#feedbtn").click(); await sleep(TICK * 3); const fr = () => [...d.querySelectorAll("#flist tr.fi")];
  ok(!q$("#feed").classList.contains("hide") && fr().length > 3, "the feed opens and lists " + fr().length + " clips");
  const heads = [...d.querySelectorAll("#flist table thead th")].map(x => x.textContent.replace(/ ▼/, ""));
  ok(!!q$("#flist table tbody") && ["Ready at", "Status", "Story", "Clip ID", "Blaze story ID", "MOS object ID", "Media", "Bulletin", "Quick test"].every((h, i) => heads[i] === h), "the feed is an HTML table with the columns: " + heads.join(" | "));
  const r0 = fr()[0]; ok(/Ready to attach|Attached/.test(cell(r0, 1)) && cell(r0, 2).length > 0 && /\S/.test(cell(r0, 3)) && /^\d+$/.test(cell(r0, 4)) && /^\d+$/.test(cell(r0, 5)) && /\.mxf$/.test(cell(r0, 6)) && cell(r0, 7).length > 0 && /^\d\d:\d\d:\d\d$/.test(cell(r0, 0)), "each row has time, status, story, clip ID, Blaze story ID, MOS object ID, media and bulletin: " + [...r0.children].map(x => x.textContent).join(" | "));
  const times = lastFeed.map(i => i.ready_at); ok(times.length > 3 && times.every((t, i) => i === 0 || times[i - 1] >= t) && fr().map(r => cell(r, 2)).join("|") === lastFeed.map(i => i.story).join("|"), "newest first: the rows follow the ready time, latest on top");
  const mos = cell(fr()[0], 5); q$("#fq").value = mos; q$("#fq").dispatchEvent(new w.Event("input")); await sleep(900);
  ok(fr().length === 1 && cell(fr()[0], 5) === mos, "searching a MOS object ID narrows the table to that one clip"); q$("#fq").value = "nonsense-zzz"; q$("#fq").dispatchEvent(new w.Event("input")); await sleep(900);
  ok(fr().length === 0 && /Nothing matches/.test(q$("#flist").textContent), "a search with no match says so"); q$("#fq").value = ""; q$("#fq").dispatchEvent(new w.Event("input")); await sleep(900);
  q$("#fst").value = "attached"; q$("#fst").dispatchEvent(new w.Event("change")); await sleep(600); ok(fr().length > 0 && fr().every(x => /Attached/.test(cell(x, 1))), "the status filter shows only attached clips"); q$("#fst").value = "all"; q$("#fst").dispatchEvent(new w.Event("change")); await sleep(600);
  const feedCounts = {}; let feedTotal = 0; new w.MutationObserver(rs => { for (const r of rs) { const k = where(r.target); feedCounts[k] = (feedCounts[k] || 0) + 1; feedTotal++; } }).observe(d.body, { subtree: true, childList: true, attributes: true, characterData: true });
  await sleep(TICK * 6); ok(feedTotal === 0, "with the feed open and nothing new, 6 refreshes made " + feedTotal + " change(s) " + (feedTotal ? JSON.stringify(feedCounts) : ""));
  inject = true; await sleep(TICK * 4); const toast = q$("#toasts .toast");
  ok(!!toast && /READY: Breaking test story/.test(toast.textContent) && /MOS-999/.test(toast.textContent), "a clip that becomes ready shows a toast with its story and MOS object ID");
  ok(d.querySelectorAll("#toasts .toast").length === 1, "...once, not on every refresh"); ok(fr()[0].classList.contains("new") && /NEW/.test(fr()[0].textContent) && cell(fr()[0], 2) === "Breaking test story" && +q$("#feedn").textContent === badge0 + 1, "...on top of the table, marked NEW, and the badge went up by one");
  fr()[0].querySelector(".ttl").click(); await sleep(900); ok(q$("#feed").classList.contains("min") && !!d.querySelector("#flist .vs") , "clicking a story title shrinks the feed to a bar to open that story (rows also have a View story button)"); ok(q$("#q").value === "" && !q$("#list").textContent.includes("No stories"), "a story that is gone leaves no dead search behind"); inject = false;
  // Quick test attach from the table: Yes / No box above the feed, No sends nothing, Yes attaches that one clip
  q$("#feedbtn").click(); await sleep(TICK * 3);
  const qrow = fr().find(r => /Ready to attach/.test(cell(r, 1)) && !r.querySelector(".qa").classList.contains("off")), qclip = qrow && cell(qrow, 3);
  ok(!!qrow, "a ready clip has an enabled Quick test attach button in its row");
  const boxOf = () => [...d.body.children].find(x => /Quick test attach\?/.test(x.textContent) && x.style.position === "fixed");
  qrow.querySelector(".qa").click(); await sleep(100); let bx = boxOf();
  ok(!!bx && bx.style.zIndex === "80" && bx.textContent.includes(qclip) && /Yes sends ONE real attach/.test(bx.textContent), "the button asks Yes / No first, names the clip, and the box sits above the feed panel");
  [...bx.querySelectorAll("button")].find(x => x.textContent === "No").click(); await sleep(TICK * 3); ok(!boxOf() && /Ready to attach/.test(cell(fr().find(r => cell(r, 3) === qclip), 1)), "No sends nothing: the clip is still ready");
  fr().find(r => cell(r, 3) === qclip).querySelector(".qa").click(); await sleep(100); [...boxOf().querySelectorAll("button")].find(x => /Yes, attach now/.test(x.textContent)).click(); await sleep(TICK * 4);
  const after = fr().find(r => cell(r, 3) === qclip); ok(!boxOf() && /Attached/.test(cell(after, 1)) && after.querySelector(".qa").classList.contains("off"), "Yes attaches that clip: its row says Attached and the button goes grey");
  after.querySelector(".qa").click(); ok(alerts.length === 1 && /Already attached/.test(alerts[0]), "a click on a grey button says why (already attached)");
  // click a story from another bulletin while the main list is narrowed to a different story: the page must still open the right one
  const tgt = lastFeed[lastFeed.length - 1], other = lastFeed.find(i => i.blaze_story_id !== tgt.blaze_story_id && i.blaze_rundown_id !== tgt.blaze_rundown_id) || lastFeed.find(i => i.blaze_story_id !== tgt.blaze_story_id);
  q$("#q").value = other.blaze_story_id; q$("#q").dispatchEvent(new w.Event("input")); await sleep(1000); ok(!w.eval("clips").some(c => c.id === tgt.id), "setup: the main list is narrowed and does not hold the story that will be clicked");
  fr().find(r => cell(r, 3) === tgt.name_id && cell(r, 2) === tgt.story).querySelector(".ttl").click(); await sleep(1500);
  ok(q$("#feed").classList.contains("min") && w.eval("sel") === tgt.id && q$("#q").value === "" && /./.test((q$("#list .sr.sel") || {}).textContent || "") && (q$("#list .sr.sel").textContent).includes(tgt.story), "clicking a story in the feed opens that very story, even from another bulletin or with a search in the way: " + (q$("#list .sr.sel") || {}).textContent);
  q$("#feedbtn").click(); await sleep(300); d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true })); ok(q$("#feed").classList.contains("hide"), "Esc closes the feed"); d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "f", bubbles: true })); ok(!q$("#feed").classList.contains("hide"), "the F key opens it");
  // v10.3.1: docked by default (page keeps room above it), minimize to a bar, maximize to full screen, Esc steps back
  const bc = d.body.classList, fc = q$("#feed").classList; ok(bc.contains("fd-dock") && !fc.contains("min") && !fc.contains("max"), "the feed opens docked at the bottom and the page makes room for it");
  q$("#feedmin").click(); ok(fc.contains("min") && bc.contains("fd-min") && !bc.contains("fd-dock") && /Ready \d+/.test(q$("#fhs").textContent), "Minimize leaves one bar with the counts");
  q$("#feedmin").click(); ok(!fc.contains("min") && bc.contains("fd-dock"), "...and the same button restores it");
  q$("#feedmax").click(); ok(fc.contains("max") && !bc.contains("fd-dock"), "Maximize fills the screen");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true })); ok(!fc.contains("max") && !fc.contains("hide"), "Esc from maximized steps back to the docked size, it does not close");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true })); ok(fc.contains("hide") && !bc.contains("fd-dock") && !bc.contains("fd-min"), "Esc again closes it and the page space is given back"); w.close();
  console.log(fails ? fails + " CHECK(S) FAILED" : "ALL CHECKS PASSED"); process.exit(fails ? 1 : 0);
})();
