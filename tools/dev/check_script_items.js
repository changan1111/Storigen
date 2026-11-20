// v10.9.7: the real page, against a real running server, in a headless DOM (jsdom): the middle pane shows every Online / Anchor text in its own box,
// a word count and reading time per box, the words-per-minute input, and the word count of the selected text. usage: node check_script_items.js <port> <email> <password>
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
    w.HTMLElement.prototype.scrollIntoView = function () {}; w.scrollTo = () => {}; } });
  const w = dom.window, d = w.document, $ = s => d.querySelector(s), $$ = s => [...d.querySelectorAll(s)]; await sleep(2000);
  const first = $$("#list .sr").find(r => /first/i.test(r.textContent)) || $("#list .sr"); first.click(); await sleep(1200);
  const boxes = () => $$("#mid .sitem"), dw = () => boxes().map(b => b.querySelector(".dw").textContent), heads = () => boxes().map(b => (b.querySelector(".sih b") || {}).textContent);
  ok(boxes().length === 2 && heads().join() === "Item 1,Item 2", "Online script: one box per item: " + heads().join(", "));
  ok(dw().join() === "6 words · 0:02,2 words · 0:01", "words and time per box at 150 words per minute: " + dw().join(" | "));
  ok(/Words: 8 {2}\| {2}Characters: \d+ {2}\| {2}Time: 0:03 {2}\| {2}Items: 2/.test($("#mid .sf").textContent), "the footer totals the tab: " + $("#mid .sf").textContent.slice(0, 80));
  const inp = $("#mid .stb input"); ok(!!inp && inp.value === "150" && /Words per minute/.test($("#mid .stb label").textContent), "the words per minute box is at the top and starts at 150");
  inp.value = "100"; inp.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(200);
  ok(dw().join() === "6 words · 0:04,2 words · 0:01" && w.localStorage.getItem("autoid_wpm") === "100", "typing 100 changes every time and is remembered: " + dw().join(" | "));
  const stx = $$("#mid .sitem .stx")[0], tn = stx.firstChild, sel = w.getSelection(), rg = d.createRange(); rg.setStart(tn, 0); rg.setEnd(tn, 13);       // "one two three" = 3 words
  const pop = () => $("#selinfo"), shown = () => !!pop() && pop().style.display === "block";
  ok(!shown(), "before a selection no count is shown");
  sel.removeAllRanges(); sel.addRange(rg); d.dispatchEvent(new w.Event("selectionchange")); await sleep(100);
  ok(shown() && pop().textContent === "3 words · 0:02" && pop().parentNode === d.body, "selected text: a floating badge says " + (pop() && pop().textContent));
  ok(!/selinfo/.test($("#mid .sf").innerHTML), "nothing about the selection is in the footer any more");
  const rg2 = d.createRange(); rg2.setStart(stx.firstChild, 0); rg2.setEnd($$("#mid .sitem .stx")[1].firstChild, 5); sel.removeAllRanges(); sel.addRange(rg2); d.dispatchEvent(new w.Event("selectionchange")); await sleep(100);
  ok(shown() && Number(/\d+/.exec(pop().textContent)[0]) === 7, "a selection over two boxes counts the words of the text only (6 + 1), not the box headers: " + pop().textContent);
  sel.removeAllRanges(); d.dispatchEvent(new w.Event("selectionchange")); await sleep(50);
  ok(!shown(), "nothing selected: the badge is gone");
  $$("#mid .tabs button")[1].click(); await sleep(300);
  ok(boxes().length === 2 && heads().join() === "Item 1,Item 3", "Anchor script: its own boxes, keeping the item numbers: " + heads().join(", "));
  ok(dw().join() === "4 words · 0:02,3 words · 0:02", "anchor words and time at 100 words per minute: " + dw().join(" | "));
  console.log(fails ? "FAILED: " + fails : "ALL CHECKS PASSED"); process.exit(fails ? 1 : 0);
})().catch(e => { console.log("ERROR", e); process.exit(1) });
