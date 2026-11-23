/* Storigen standalone sample: answers the dashboard's /api/* calls in the browser, with made-up stories.
   Injected by tools/make_standalone.py in front of the real page script. Nothing here is used by the live server. */
(function () {
  "use strict";
  const pad = (n, w) => String(n).padStart(w || 2, "0"), now = new Date();
  const DAY = now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
  const at = (h, m) => new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m).toISOString();
  const ago = m => new Date(Date.now() - m * 60000).toISOString();
  const SHOWS = [{ id: "101", name: "Morning Headlines", start: at(6, 0) }, { id: "102", name: "Midday News", start: at(12, 30) },
    { id: "103", name: "Prime Time Bulletin", start: at(18, 30) }, { id: "104", name: "9 PM Bulletin", start: at(21, 0) }];
  // [show, slug, story name, state, anchor script, online script]
  const S = [
    [0, "RAIN ALERT COASTAL", "Heavy rain alert for coastal districts", "ATTACHED", "Heavy rain is expected along the coast tonight. Fishermen are advised not to go to sea.", "Orange alert issued for three coastal districts."],
    [0, "BUDGET SESSION OPENS", "State assembly budget session opens", "ATTACHED", "The budget session of the state assembly began this morning amid sharp exchanges.", "Opposition walks out on day one."],
    [0, "METRO PHASE 2 UPDATE", "Metro phase 2 work progress", "ATTACHED", "Work on the second phase of the metro is running ahead of schedule, officials say.", ""],
    [0, "AIRPORT NEW TERMINAL", "New airport terminal opens", "EXPORTING", "The new terminal handles its first international flights from today.", "Passengers praise shorter queues."],
    [1, "FARMERS PROTEST VNR", "Farmers protest at district office", "ON_NITRO", "Farmers gathered outside the district office demanding a higher support price.", "Police kept a close watch; traffic was diverted for two hours."],
    [1, "CRICKET T20 PREVIEW", "T20 series preview", "ON_NITRO", "The T20 series starts tomorrow. Both teams have named unchanged squads.", "Pitch report: a dry surface that should help spinners."],
    [1, "SCHOOL EXAM RESULTS", "Class 12 results declared", "ATTACHED", "Class 12 results were declared this morning with a pass rate of 91 percent.", "Girls outperform boys for the fifth year."],
    [1, "PETROL PRICE HIKE", "Fuel price revised", "WAITING_FOR_CLIP", "Petrol and diesel prices were revised again overnight.", ""],
    [1, "TEMPLE FESTIVAL CROWD", "Temple festival draws huge crowd", "VERIFIED", "Lakhs of devotees thronged the temple on the main festival day.", "Extra buses and special trains were arranged."],
    [2, "CITY FLOOD RELIEF", "Flood relief camps", "ON_NITRO", "Relief camps in the city now house more than two thousand families.", "Volunteers distribute food packets from 5 am."],
    [2, "HOSPITAL FIRE DRILL", "Hospital fire safety audit", "NEEDS_DESK", "A fire safety audit of government hospitals found gaps in ten of them.", "Report to be tabled next week."],
    [2, "TECH PARK INVESTMENT", "Tech park investment announced", "ATTACH_SUBMITTED", "A leading software firm announced a new tech park with five thousand jobs.", "Foundation stone to be laid next month."],
    [2, "ELECTION RALLY LIVE", "Election rally live report", "EXPORTING", "Party leaders addressed rallies in four constituencies today.", ""],
    [2, "RIVER CLEANUP DRIVE", "River cleanup drive", "WAITING_FOR_CLIP", "Thousands joined a weekend drive to clean the riverbank.", "Collected waste crossed twelve tonnes."],
    [2, "FILM AWARDS NIGHT", "Film awards night highlights", "ATTACHED", "The annual film awards were held in the city last night.", "Best film went to a small-budget drama."],
    [3, "BULLETIN HEADLINES", "Headlines at nine", "WAITING_FOR_CLIP", "These are the top stories at nine tonight.", ""],
    [3, "WEATHER WEEKEND", "Weekend weather outlook", "WAITING_FOR_CLIP", "Clear skies are likely across the state through the weekend.", "Temperatures to stay near normal."],
    [3, "STOCK MARKET CLOSE", "Markets close higher", "QUARANTINED", "The main index closed higher on strong buying in banking shares.", "Banking index up 1.4 percent."],
    [3, "SPORTS ROUNDUP", "Sports roundup", "WAITING_FOR_CLIP", "A quick look at the day in sport.", "Football league: leaders drew 1-1."],
    [3, "BULLETIN CLOSE", "Closing items", "WAITING_FOR_CLIP", "That was the nine o'clock bulletin. Good night.", ""]
  ];
  const ACT = ["ON_NITRO", "NEEDS_DESK", "ATTACH_SUBMITTED", "QUARANTINED"], DONE = ["ATTACHED"], NIT = ["ON_NITRO"], ATTN = ["NEEDS_DESK", "QUARANTINED"];
  const FOLDERS = ["NEWS", "NEWS", "PROGRAMS", "PROMO"], pos = {};
  const C = S.map((r, i) => {
    const sh = SHOWS[r[0]], n = 12 + i * 3, p = pos[r[0]] = (pos[r[0]] || 0) + 1, did = DAY.replace(/-/g, "") + "_" + pad(n, 4) + String.fromCharCode(65 + (n * 7) % 26);
    return { id: i + 1, display_id: did, name_id: did + "_" + r[1].replace(/[^A-Z0-9]+/g, "_"), version: 1, state: r[3], slug: r[1], story_title: r[2], anchor_script: r[4], online_script: r[5],
      anchor_len: r[4].length, online_len: r[5].length, position: p, show_start: sh.start, rundown: sh.name, blaze_rundown_id: sh.id, blaze_story_id: String(2669100 + i * 7), slug_id: String(880000 + i),
      folder: FOLDERS[i % 4], deleted: false, typed: false, qa_state: null, why: null, error: null, mos_object_id: null, item_id: null, attach_dur: null, blaze_clip_id: null, t: ago(90 - i * 3) };
  });
  const rank = { WAITING_FOR_CLIP: 0, EXPORTING: 1, VERIFIED: 1, ON_NITRO: 2, ATTACH_SUBMITTED: 3, ATTACHED: 4 };
  function derive(c) {      // the four-step strip, ids and messages that follow from the state
    const k = rank[c.state] != null ? rank[c.state] : 1;
    c.stages = { export: c.state !== "WAITING_FOR_CLIP", export_folder: c.folder, onair: k >= 2 || c.state === "NEEDS_DESK", nitro: k >= 2 && c.state !== "NEEDS_DESK", attached: c.state === "ATTACHED" };
    const has = c.stages.nitro; c.mos_object_id = has ? String(4400000 + c.id * 17) : null;
    c.item_id = c.state === "ATTACHED" ? String(910000 + c.id) : null; c.attach_dur = c.state === "ATTACHED" ? 38 + c.id * 4 : null; c.blaze_clip_id = c.state === "ATTACHED" ? "BC" + (70000 + c.id) : null;
    c.error = c.state === "NEEDS_DESK" ? "The file is on Nitro but Blaze does not list a media object with this ID yet." : c.state === "QUARANTINED" ? "File name has a mistyped check letter: the file starts with " + c.display_id.slice(0, -1) + "X." : null;
    return c;
  }
  C.forEach(derive);
  // Story Media Gallery sample: the first story has three clips: the plain clip (BASE), an added clip (_V01) and an update (_U01)
  C.forEach(c => { c.story_id = c.id; });
  { const b = C[0]; [[2001, "_V01", "ATTACHED"], [1001, "_U01", "ON_NITRO"]].forEach((x, k) => { const n = C.length + 1; C.push(derive(Object.assign({}, b, { id: n, display_id: b.display_id + x[1], name_id: b.name_id + x[1], version: x[0], state: x[2], story_id: b.story_id, t: ago(40 - k * 10) }))); }); }
  const siblings = c => C.filter(x => x.story_id === c.story_id);
  C.forEach(c => { const l = siblings(c); c.story_clips = l.length; c.story_update = l.some(x => x.version > 1000 && x.version < 2000) ? "U01" : null; c.vlabel = c.version > 2000 ? "V" + pad(c.version % 1000) : c.version > 1000 ? "U" + pad(c.version % 1000) : null; });
  const SJ = [];      // v10.11.0 sample Support requests (the Delete icon)
  const json = (d, s) => new Response(JSON.stringify(d), { status: s || 200, headers: { "Content-Type": "application/json" } });
  const hm = iso => { const d = new Date(iso); return pad(d.getHours()) + ":" + pad(d.getMinutes()); };
  const hay = c => [c.slug, c.story_title, c.display_id, c.name_id, c.mos_object_id, c.item_id, c.blaze_story_id, c.slug_id, c.blaze_rundown_id, c.rundown, hm(c.show_start), hm(c.show_start).replace(":", "")].join(" ").toLowerCase();
  const inflt = (f, st) => f === "all" || (f === "action" && ACT.includes(st)) || (f === "nitro" && NIT.includes(st)) || (f === "attention" && ATTN.includes(st)) || (f === "done" && DONE.includes(st)) || (f === "waiting" && !ACT.includes(st) && !DONE.includes(st));
  const tally = list => { const n = (...s) => list.filter(c => s.includes(c.state)).length; return { all: list.length, action: n(...ACT), done: n(...DONE), waiting: list.length - n(...ACT) - n(...DONE), on_nitro: n("ON_NITRO"), needs_desk: n("NEEDS_DESK", "QUARANTINED"), attached: n("ATTACHED") }; };
  function clipsQuery(q) {
    const day = q.get("day") ? q.get("day").replace(/^(\d{4})(\d\d)(\d\d)$/, "$1-$2-$3") : DAY, f = (q.get("filter") || "all").toLowerCase(), show = (q.get("show") || "").trim(), words = (q.get("q") || "").toLowerCase().split(/\s+/).filter(Boolean).slice(0, 8);
    const per = Math.max(0, Math.min(parseInt(q.get("per_page") || "0", 10) || 0, 200)), all = day === DAY ? C : [];
    const byQ = all.filter(c => words.every(w => hay(c).includes(w))), byShow = show ? byQ.filter(c => c.blaze_rundown_id === show) : byQ, rows = byShow.filter(c => inflt(f, c.state));
    const pages = per ? Math.max(1, Math.ceil(rows.length / per)) : 1, page = Math.min(Math.max(1, parseInt(q.get("page") || "1", 10) || 1), pages);
    let out = rows.slice().sort((a, b) => per ? (ACT.slice(0, 3).includes(a.state) ? 0 : 1) - (ACT.slice(0, 3).includes(b.state) ? 0 : 1) || +a.blaze_rundown_id - +b.blaze_rundown_id || a.position - b.position : a.id - b.id);
    if (per) out = out.slice((page - 1) * per, page * per);
    const shows = SHOWS.filter(s => all.some(c => c.blaze_rundown_id === s.id)).map(s => Object.assign({}, s, { n: all.filter(c => c.blaze_rundown_id === s.id).length }));
    const bulletins = shows.map(s => { const l = byQ.filter(c => c.blaze_rundown_id === s.id), n = (...st) => l.filter(c => st.includes(c.state)).length;
      return Object.assign({}, s, { n: l.length, m: l.filter(c => inflt(f, c.state)).length, nitro: n(...NIT), attn: n(...ATTN), done: n(...DONE), wait: l.filter(c => !ACT.includes(c.state) && !DONE.includes(c.state)).length }); }).filter(b => b.m);
    return { day, clips: out.map(c => Object.assign({}, c)), total: rows.length, page, pages, per_page: per, counts: tally(byShow), day_counts: tally(all), shows, bulletins };
  }
  function history(c) {
    const st = c.stages, f = c.stage_file || (st.export ? { n: c.name_id + (st.nitro ? ".mxf" : ".mov"), where: st.nitro ? "Nitro" : "Playout" } : null), t = c.t;
    const step = (key, label, detail, time, done, problem) => ({ key, label, detail, time: time || null, done: !!done, problem: !!problem });
    const steps = [step("story", "Story received from Blaze", "Story " + c.blaze_story_id + " in " + c.rundown + ", row " + c.position, t, 1), step("id", "Auto-ID generated", c.name_id, t, 1),
      step("export", "Export detected", st.export ? "File seen in Playout: " + c.name_id + ".mov" : "Waiting for the export with exactly this name", st.export ? ago(60) : null, st.export),
      step("nitro", "Nitro file detected", st.nitro ? "Converted file: " + c.name_id + ".mxf" : "Waiting for the converted file on Nitro", st.nitro ? ago(45) : null, st.nitro),
      step("attach", c.state === "ATTACHED" ? "Attachment verified" : "Attachment in the story", c.state === "ATTACHED" ? "Attached (desk) · MOS object " + c.mos_object_id + " · item " + c.item_id + " · duration " + c.attach_dur + " s" : "Waiting for the desk (or the live attach) to put the clip in the story", c.state === "ATTACHED" ? ago(20) : null, c.state === "ATTACHED")];
    if (c.error) steps.push(step("problem", "Needs the desk", c.error, null, false, true));
    const keys = ["slug", "story_title", "online_script", "anchor_script", "show_start", "rundown", "blaze_rundown_id", "blaze_story_id", "position", "deleted", "mos_object_id", "item_id", "attach_dur", "blaze_clip_id"], clip = {}; keys.forEach(k => clip[k] = c[k]); clip.script_at = ago(30);
    const story_clips = siblings(c).slice().sort((a, b) => (a.version !== 1) - (b.version !== 1) || a.id - b.id).map(x => ({ id: x.id, display_id: x.display_id, name_id: x.name_id, version: x.version, role: x.version === 1 ? "original" : x.version < 2000 ? "update" : "additional", label: x.version === 1 ? "BASE" : x.vlabel,
      state: x.state, mos_object_id: x.mos_object_id, item_id: x.item_id, attach_dur: x.attach_dur, blaze_clip_id: x.blaze_clip_id, on_nitro: !!x.stages.nitro, duration_s: x.stages.nitro ? 41 + x.id * 3 : null, file: x.stages.nitro ? x.name_id + ".mxf" : null }));
    return { id: c.id, display_id: c.display_id, name_id: c.name_id, state: c.state, steps, story_clips, clip, file: f ? { name: f.n, where: f.where, size: 48e6, duration_s: st.nitro ? 41 + c.id * 3 : null } : null };
  }
  const EV = [["editor1@station.com", "clip_attached", { clip: "RAIN ALERT COASTAL" }], ["system", "on_nitro", { clip: "FARMERS PROTEST VNR" }], ["system", "on_nitro", { clip: "CITY FLOOD RELIEF" }], ["system", "needs_desk", { clip: "HOSPITAL FIRE DRILL" }], ["editor2@station.com", "marked_attached", { clip: "SCHOOL EXAM RESULTS" }]];
  const clipById = id => C.find(c => c.id === +id);
  const T = { WAITING_FOR_CLIP: "EXPORTING", EXPORTING: "ON_NITRO", VERIFIED: "ON_NITRO" };
  setInterval(() => { const c = C.find(x => T[x.state]); if (c) { c.state = T[c.state]; derive(c); } }, 45000);      // one clip moves on every 45 s so the "ready on Nitro" notice can be seen
  // Ready feed (v10.2.0, table in v10.3.0): the clips whose file is in Blaze's media list (NITRO green), newest first, like GET /api/feed on the real server
  const FEEDST = c => c.state === "ATTACHED" ? "ATTACHED" : (c.state === "NEEDS_DESK" || c.state === "QUARANTINED") ? "NEEDS_DESK" : c.qa_state === "REQUESTED" ? "REQUESTED" : c.state === "ATTACH_SUBMITTED" ? "SUBMITTED" : "READY";
  const FEEDTXT = { READY: "Ready to attach", REQUESTED: "Attach requested", SUBMITTED: "Attach sent", ATTACHED: "Attached", NOT_SENT: "Not sent", NEEDS_DESK: "Needs desk" };
  const FEEDGRP = { ready: ["READY", "REQUESTED", "SUBMITTED"], attached: ["ATTACHED"], problem: ["NOT_SENT", "NEEDS_DESK"] };
  function feedQuery(q) {
    const day = q.get("day") ? q.get("day").replace(/^(\d{4})(\d\d)(\d\d)$/, "$1-$2-$3") : DAY, words = (q.get("q") || "").toLowerCase().split(/\s+/).filter(Boolean).slice(0, 8), st = (q.get("status") || "all").toLowerCase();
    const limit = Math.max(1, Math.min(parseInt(q.get("limit") || "100", 10) || 100, 300)), base = (day === DAY ? C : []).filter(c => c.mos_object_id && !c.deleted), counts = { ready: 0, attached: 0, problem: 0, all: base.length };
    base.forEach(c => { const k = FEEDST(c); for (const g in FEEDGRP) if (FEEDGRP[g].includes(k)) counts[g]++; });
    const items = base.filter(c => words.every(w => [c.slug, c.story_title, c.display_id, c.name_id, c.mos_object_id, c.name_id + ".mxf", c.blaze_story_id, c.rundown].join(" ").toLowerCase().includes(w)))
      .filter(c => st === "all" || (FEEDGRP[st] || []).includes(FEEDST(c))).sort((a, b) => b.t.localeCompare(a.t) || b.id - a.id)
      .map(c => { const k = FEEDST(c); return { id: c.id, display_id: c.display_id, name_id: c.name_id, version: 1, blaze_story_id: c.blaze_story_id, story: c.story_title || c.slug, slug: c.slug, bulletin: c.rundown, start_at: c.show_start, blaze_rundown_id: c.blaze_rundown_id, position: c.position, state: c.state, qa_state: c.qa_state || null, typed: !!c.typed,
        mos_object_id: c.mos_object_id, media_name: c.name_id + ".mxf", ready_at: c.t, attached_at: k === "ATTACHED" ? c.t : null, status: k, status_text: FEEDTXT[k], reason: k === "NEEDS_DESK" ? c.error : null }; });
    return { day, items: items.slice(0, limit), total: items.length, counts, limit };
  }
  const realFetch = window.fetch.bind(window);
  window.fetch = async function (u, o) {
    u = String(u); if (u.indexOf("/api/") !== 0) return realFetch(u, o);
    const [path, qs] = u.split("?"), q = new URLSearchParams(qs || ""), post = o && o.method === "POST"; let m;
    if (path === "/api/me") return json({ email: "demo@storigen.local", name: "Demo", role: "admin", perms: ["view", "version", "attach", "events"], valid_upto: null, days_left: null });
    if (path === "/api/config") return json({ story_url: "sample", version: "10.18.2 sample", link_mode: "story_id", watcher_enabled: true, manual_enabled: false, quick_attach: true, support: true, script_labels: ["Online script", "Anchor script"], version_suffix: true });
    if (path === "/api/status") return json({ problems: [] });
    if (path === "/api/rundowns") return json(SHOWS.map(s => s.name));
    if (path === "/api/feed") return json(feedQuery(q));
    if (path === "/api/clips") return json(clipsQuery(q));
    if (path === "/api/events") return json(EV.map((e, i) => ({ time: ago(3 + i * 7), actor: e[0], action: e[1], details: e[2] })));
    if (path === "/api/login" || path === "/api/logout") return json({ ok: true });
    if ((m = /^\/api\/clips\/(\d+)\/history$/.exec(path))) { const c = clipById(m[1]); return c ? json(history(c)) : json({ detail: "no such clip" }, 404); }
    if (post && (m = /^\/api\/clips\/(\d+)\/(attached|quickattach)$/.exec(path))) { const c = clipById(m[1]); if (c) { c.state = "ATTACHED"; c.stage_file = null; derive(c); c.mos_object_id = c.mos_object_id || String(4400000 + c.id * 17); } return json({ ok: true }); }
    // v10.11.0: the Clip assistant (read-only, /api/bot/*) and the Delete icon (the Support list / remove calls), answered from the sample stories
    if (path === "/api/bot/bulletins" || path === "/api/support/bulletins") return json({ day: DAY, wait_min: 60, bulletins: SHOWS.map(s => ({ id: s.id, name: s.name, start_at: s.start, aired: new Date(s.start) < new Date(Date.now() - 3600000), stories: new Set(C.filter(c => c.blaze_rundown_id === s.id).map(c => c.story_id)).size })).filter(b => b.stories) });
    if (path === "/api/bot/stories" || path === "/api/support/stories") { const sh = SHOWS.find(x => x.id === q.get("rundown")); if (!sh) return json({ detail: "unknown bulletin" }, 404);
      const seen = new Set(), st = C.filter(c => c.blaze_rundown_id === sh.id && !seen.has(c.story_id) && seen.add(c.story_id)).map(c => ({ id: c.blaze_story_id, title: c.slug, pos: c.position })); return json({ stories: st, aired: new Date(sh.start) < new Date(Date.now() - 3600000) }); }
    if (path === "/api/bot/story") { const c = C.find(x => x.blaze_rundown_id === q.get("rundown") && x.blaze_story_id === q.get("story") && x.version === 1); if (!c) return json({ detail: "unknown story" }, 404);
      const rows = siblings(c), strip = n => n.replace(/(_[UV]\d+)+$/i, ""), base = strip(c.name_id), has = (a, b) => rows.some(x => x.version >= a && x.version < b), top = (a, b) => Math.max(0, ...rows.filter(x => x.version >= a && x.version < b).map(x => x.version));
      const mkslot = (key, label, cur, u, nameFor) => ({ key, label, current: cur.name_id, state: cur.state, in_story: cur.state === "ATTACHED" && !cur.replaced, update_no: u, next_u: u + 1, next_u_name: nameFor(u + 1) });
      const mainRows = rows.filter(x => x.version === 1 || (x.version > 1000 && x.version < 2000)).sort((a, b) => a.version - b.version), mc = mainRows[mainRows.length - 1];
      const vs = rows.filter(x => x.version > 2000 && x.version < 3000).sort((a, b) => a.version - b.version), nv = (vs.length ? vs[vs.length - 1].version - 2000 : 0) + 1;
      return json({ story: { id: c.blaze_story_id, title: c.slug, bulletin: c.rundown, aired: new Date(c.show_start) < new Date(Date.now() - 3600000) }, base, day: DAY,
        clips: rows.slice().sort((a, b) => (a.version !== 1) - (b.version !== 1) || a.version - b.version).map(x => ({ name: x.name_id, version: x.version, state: x.state, replaced: !!x.replaced })),
        main: mkslot("main", "Main clip", mc, mc.version > 1000 ? mc.version - 1000 : 0, n => base + "_U" + pad(n)),
        added: vs.map(v => mkslot("V" + pad(v.version - 2000), "Added clip V" + pad(v.version - 2000), v, 0, n => base + "_V" + pad(v.version - 2000) + "_U" + pad(n))),
        next_v: base + "_V" + pad(nv), next_v_no: nv, bulletins: [{ name: c.rundown, aired: false }], version_suffix: true }); }
    // v10.12.0 sample answers: name check, quality check, frames, analytics (no ffmpeg or Groq in the sample)
    if (path === "/api/bot/checkname") { const n = q.get("name") || ""; return json({ ok: /_V\d\d$/.test(n), kind: "append", does: "adds a clip", messages: ["Sample answer: the real server checks the name against the story."], fix: null, base: "sample" }); }
    if ((m = /^\/api\/clips\/(\d+)\/quality$/.exec(path))) return json({ verdict: "warn", facts: {}, checks: [{ name: "Picture", level: "ok", text: "1920x1080 · 25 fps" }, { name: "Sound", level: "ok", text: "Loudness -23.1 LUFS" }, { name: "Black", level: "warn", text: "Black at the start or end: 1.4 s at 0:00." }, { name: "Length", level: "ok", text: "File 48 s · attached 48 s" }] });
    if ((m = /^\/api\/clips\/(\d+)\/frames$/.exec(path))) return json({ duration_s: 48, frames: [], summary: q.get("ai") === "1" ? "Sample: a reporter speaks in front of a crowd." : undefined, tags: ["sample"], model: "sample", ai_error: q.get("ai") === "1" ? undefined : undefined });
    if (path === "/api/analytics") { const z = { n: 0, median: null, p90: null }, blk = { clips: C.length, attached: C.filter(c => c.state === "ATTACHED").length, waiting: 0, problem: 0, late: 0, updates: 0, added: 0, to_nitro: z, to_attach: { n: 1, median: 12.5, p90: 31 }, nitro_to_attach: z };
      return json({ total: blk, days: [{ day: DAY, ...blk }], shows: SHOWS.map(s => ({ show: s.name, ...blk })), slowest: [], from: DAY, to: DAY, days_asked: 7 }); }
    if (path === "/api/support/media") return json({ media: [], days: 2 });
    if (path === "/api/support/jobs") return json({ jobs: SJ.filter(j => j.kind !== "LIST").reverse(), open: 0 });
    if (post && path === "/api/support/list") { const b = JSON.parse(o.body || "{}"), cl = C.filter(x => x.blaze_story_id === b.story && x.blaze_clip_id && !x.replaced);
      SJ.push({ id: SJ.length + 1, kind: "LIST", state: "DONE", result: { clips: cl.map(x => ({ id: x.blaze_clip_id, mos: x.mos_object_id, title: x.name_id, dur_s: x.attach_dur })), shows: [b.rundown], show_names: [(SHOWS.find(s => s.id === b.rundown) || {}).name || b.rundown], story_title: (cl[0] || {}).slug } }); return json({ id: SJ.length }); }
    if ((m = /^\/api\/support\/jobs\/(\d+)$/.exec(path))) { const j = SJ[+m[1] - 1]; return j ? json(j) : json({ detail: "unknown request" }, 404); }
    if (post && path === "/api/support/remove") { const b = JSON.parse(o.body || "{}"), c = C.find(x => x.blaze_clip_id === b.clip_id); if (c) { c.state = "NEEDS_DESK"; c.error = "Sample: the clip was deleted from the story by the Delete icon."; c.blaze_clip_id = null; c.item_id = null; c.attach_dur = null; c.stages.attached = false; }
      SJ.push({ id: SJ.length + 1, kind: "REMOVE", state: "DONE", story: (c || {}).slug, clip_title: b.clip_title, by_user: "demo", msg: "Sample: deleted, nothing was sent to Blaze." }); return json({ ok: true, id: SJ.length }); }
    return json({ detail: "Not available in the sample dashboard (no server behind it)." }, 400);
  };
  window.open = () => { alert("Sample dashboard: in the live app this opens the story in Blaze."); return null; };
  const click = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {      // Export CSV: build the file here instead of asking the server
    if (/\/api\/clips\.csv/.test(this.getAttribute("href") || "")) {
      const q = new URLSearchParams((this.getAttribute("href").split("?")[1]) || ""), rows = clipsQuery(q).clips, e = v => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"';
      const csv = ["clip_id,state,bulletin,story,rundown_row"].concat(rows.map(c => [c.name_id, c.state, hm(c.show_start) + " " + c.rundown, c.slug, c.position].map(e).join(","))).join("\n");
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "storigen_sample_clips.csv"; click.call(a); return;
    }
    return click.call(this);
  };
  document.addEventListener("click", e => { const a = e.target.closest && e.target.closest("#rep"); if (a) { e.preventDefault(); alert("Sample dashboard: the Tool vs desk report is written by the poller in the live app."); } }, true);
  document.addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("div"); b.textContent = "SAMPLE DATA · standalone, no server";
    b.style.cssText = "position:fixed;left:.6rem;bottom:.6rem;z-index:99;background:#13233f;color:#9fe3bb;border:1px solid #2f7a52;border-radius:999px;padding:.25rem .7rem;font:700 .7rem system-ui,sans-serif;letter-spacing:.04em;pointer-events:none;opacity:.92";
    document.body.append(b);
  });
})();
