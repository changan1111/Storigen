"""v10.16.0: the AI standards check (violence, sexual content, distress that is NOT blurred). Groq is replaced by a stand-in everywhere: no network. ffmpeg is real (frames are cut from generated clips)."""
import base64, json, pathlib, shutil, sys, urllib.error
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_preview import mxf, clip_on_nitro, FF
from test_server import Srv
from test_insights import Resp, http_err, KEY, with_key, tree, nitro, need_ff
from autoid_lite import standards, clipsummary
from autoid_lite.common import HttpError

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
CATS = ["violence", "sexual", "distress"]
def item(n, v="none", s="none", d="none", note=""): return {"n": n, "violence": v, "sexual": s, "distress": d, "note": note}
def reply(*items): return json.dumps({"frames": list(items)})
def chat(text): return Resp({"choices": [{"message": {"content": text}}]})

# ------------------------------------------------------------------------------------------------ plan and prompt
def test_frame_plan_is_about_one_every_two_seconds_with_a_cap():
    ts, iv = standards.plan(60); assert len(ts) == 30 and iv == 2.0 and ts[0] == 1.0 and ts[-1] == 59.0
    ts, iv = standards.plan(10); assert len(ts) == 5 and iv == 2.0
    ts, iv = standards.plan(200); assert len(ts) == 30 and iv == 6.67, "a long clip gets a wider gap, and the page is told"
    assert standards.plan(0) == ([0.0], 2.0) and len(standards.plan(1.2)[0]) == 1
    assert len(standards.plan(60, cap=8)[0]) == 8

def test_the_prompt_asks_for_strict_json_and_leans_to_visible(monkeypatch):
    p = standards.prompt(3, CATS); assert "3 attached pictures" in p and "not sure" in p and '"visible"' in p and "do not name any person" in p and "ONLY JSON" in p
    for c in CATS: assert "- %s:" % c in p
    assert "heartbreaking" in p and "blood" in p and "exposed" in p
    assert "newsroom's own standard" not in p and "no soldiers' faces" in standards.prompt(2, CATS, "no soldiers' faces")
    monkeypatch.setenv("STANDARDS_CATEGORIES", "violence, bogus"); assert standards.categories() == ["violence"]
    monkeypatch.setenv("STANDARDS_CATEGORIES", "bogus"); assert standards.categories() == CATS, "nothing usable: all three"
    monkeypatch.setenv("STANDARDS_NOTE", "x" * 900); assert len(standards.prompt(2, CATS).split("standard: ")[1].split("\n")[0]) <= 600

# ------------------------------------------------------------------------------------------------ parsing: strict, never 'none' by accident
def test_a_good_answer_is_read_even_in_a_code_fence():
    t = reply(item(1, v="visible", note=" a  man hurt "), item(2, s="blurred"), item(3))
    out = standards.parse_batch("```json\n" + t + "\n```", 3, CATS); assert out[0]["violence"] == "visible" and out[0]["note"] == "a man hurt" and out[1]["sexual"] == "blurred" and out[2]["distress"] == "none"
    assert standards.parse_batch("Here you go: " + t + " hope it helps", 3, CATS)[0]["violence"] == "visible"
    assert standards.parse_batch(reply(item(1, v="VISIBLE ")), 1, CATS)[0]["violence"] == "visible"

def test_anything_unreadable_is_unreadable_never_none():
    for bad in ("I'm sorry, I can't help with that.", "", "{not json", '{"frames": "x"}', '{"other": 1}', "[1,2]", None): assert standards.parse_batch(bad, 2, CATS) == [None, None], repr(bad)
    out = standards.parse_batch(reply(item(1), {"n": 2, "violence": "maybe", "sexual": "none", "distress": "none"}), 3, CATS); assert out[0] and out[1] is None and out[2] is None, "an invalid value or a missing frame is unreadable"
    out = standards.parse_batch(reply(item(1, v="visible"), item(1), item(9)), 2, CATS); assert out[0]["violence"] == "visible" and out[1] is None, "a repeated or out-of-range frame number is ignored"
    assert standards.parse_batch(reply({"n": 1, "violence": "none"}), 1, CATS) == [None], "a category the AI left out is unreadable"
    assert standards.parse_batch(reply(item(1, v="visible")), 1, ["violence"])[0] == {"violence": "visible", "note": ""}

# ------------------------------------------------------------------------------------------------ judging
def fr(t, **k): return {"t": t, "res": None if k.get("none") else dict({c: "none" for c in CATS}, note=k.get("note", ""), **{c: v for c, v in k.items() if c in CATS}), "error": "why"}

def test_neighbouring_frames_make_one_flag_and_the_worst_come_first():
    frames = [fr(1), fr(3, violence="visible", note="fight"), fr(5, violence="visible"), fr(7, violence="blurred"), fr(9, sexual="visible"), fr(11, none=True), fr(13, none=True), fr(15), fr(17, violence="visible")]
    j = standards.judge(frames, CATS)
    got = [(f["category"], f["verdict"], f["t"], f["last"], f["frames"]) for f in j["flags"]]
    assert got == [("violence", "visible", 3, 5, 2), ("sexual", "visible", 9, 9, 1), ("violence", "visible", 17, 17, 1), ("all", "unchecked", 11, 13, 2), ("violence", "blurred", 7, 7, 1)], got
    assert j["flags"][0]["note"] == "fight" and j["flags"][3]["note"] == "why"
    assert j["counts"] == {"frames": 9, "unchecked": 2, "visible": 3, "blurred": 1}
    assert standards.judge([fr(1), fr(3)], CATS)["flags"] == [], "nothing found is an empty list, and the page still never says clear"
    assert standards.judge([fr(1, violence="visible"), fr(3, violence="blurred"), fr(5, violence="visible")], CATS)["counts"]["visible"] == 2, "a blurred frame between breaks the run"

# ------------------------------------------------------------------------------------------------ the check with real frames and a stand-in Groq
def groq(answers, seen=None):
    it = iter(answers)
    def op(req, timeout=None):
        body = json.loads(req.data)
        if seen is not None: seen.append({"auth": req.get_header("Authorization"), "n": len([p for p in body["messages"][0]["content"] if p["type"] == "image_url"]), "model": body["model"], "text": body["messages"][0]["content"][0]["text"]})
        a = next(it)
        if isinstance(a, Exception): raise a
        return chat(a)
    return op

@need_ff
def test_check_sends_batches_of_five_and_flags_what_is_not_blurred(tmp_path, monkeypatch):
    d = nitro(tmp_path, monkeypatch); f = d / "221126_WAR.mxf"; mxf(f, 12); before = tree(tmp_path); with_key(monkeypatch); seen = []
    op = groq([reply(item(1), item(2, v="visible", note="man on the ground, blood"), item(3, v="visible"), item(4, s="blurred"), item(5, d="visible", note="woman screaming at a body")), "I'm sorry, I can't help with that."], seen)
    r = standards.check(str(f), opener=op)
    assert [x["n"] for x in seen] == [5, 1] and all(x["auth"] == "Bearer " + KEY and x["model"] == clipsummary.DEFAULT_MODEL for x in seen) and "5 attached pictures" in seen[0]["text"]
    assert r["interval_s"] == 2.0 and r["counts"] == {"frames": 6, "unchecked": 1, "visible": 2, "blurred": 1} and r["categories"] == CATS
    fl = {(x["category"], x["verdict"]): x for x in r["flags"]}
    assert fl[("violence", "visible")]["t"] == 3.0 and fl[("violence", "visible")]["last"] == 5.0 and fl[("violence", "visible")]["note"] == "man on the ground, blood"
    assert fl[("distress", "visible")]["t"] == 9.0 and fl[("sexual", "blurred")]["t"] == 7.0 and fl[("all", "unchecked")]["t"] == 11.0, "a refused batch is NOT CHECKED, never fine"
    assert "refused" in fl[("all", "unchecked")]["note"] or "expected form" in fl[("all", "unchecked")]["note"]
    assert [x["verdict"] for x in r["flags"]] == ["visible", "visible", "unchecked", "blurred"], "worst first"
    assert all(base64.b64decode(x["jpeg_b64"])[:2] == b"\xff\xd8" for x in r["flags"]) and KEY not in json.dumps(r)
    assert tree(tmp_path) == before, "nothing stored"

@need_ff
def test_a_wrong_key_stops_everything_and_a_later_failure_keeps_what_was_found(tmp_path, monkeypatch):
    d = nitro(tmp_path, monkeypatch); f = d / "221126_WAR.mxf"; mxf(f, 12); with_key(monkeypatch)
    with pytest.raises(HttpError) as ei: standards.check(str(f), opener=groq([http_err(401)]))
    assert ei.value.status == 502 and "key" in ei.value.detail and KEY not in ei.value.detail
    with_key(monkeypatch); r = standards.check(str(f), opener=groq([reply(item(1, v="visible"), item(2), item(3), item(4), item(5)), http_err(429)]))
    assert r["counts"]["visible"] == 1 and r["counts"]["unchecked"] == 1 and "too many requests" in r["ai_error"], "the first batch's findings stay; the rest is listed as not checked"
    with_key(monkeypatch); r = standards.check(str(f), opener=groq([urllib.error.URLError("down")]))
    assert r["counts"]["unchecked"] == 6 and "could not be reached" in r["ai_error"] and all(x["verdict"] == "unchecked" for x in r["flags"]), "Groq down: everything NOT CHECKED, nothing pretends to be fine"

@need_ff
def test_the_hourly_ceiling_and_the_time_limit_leave_the_rest_unchecked(tmp_path, monkeypatch):
    d = nitro(tmp_path, monkeypatch); f = d / "221126_WAR.mxf"; mxf(f, 12); with_key(monkeypatch, GROQ_MAX_PER_HOUR="1")
    r = standards.check(str(f), opener=groq([reply(*[item(i) for i in range(1, 6)])])); assert r["counts"]["unchecked"] == 1 and "hourly limit" in r["ai_error"]
    with_key(monkeypatch, STANDARDS_MAX_SECONDS="20"); ticks = iter([0, 0, 500, 500, 500]); r = standards.check(str(f), opener=groq([reply(*[item(i) for i in range(1, 6)])]), now=lambda: next(ticks))
    assert r["counts"]["unchecked"] == 1 and "time limit" in r["ai_error"]

def test_no_key_no_check(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False); assert not standards.available()
    with pytest.raises(HttpError) as ei: standards.check(str(tmp_path / "x.mxf")); assert ei.value.status == 503

# ------------------------------------------------------------------------------------------------ the switch and the endpoint
def test_the_switch_is_off_by_default_and_admin_only_and_logged(tmp_path):
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    f = s.call("GET", "/api/features")[1]; assert f["standards_ai"] == {"on": False} and f["missing_board"]["on"] is True and f["smoke_test"]["on"] is True, "the two older features stay on, this one starts off"
    assert s.call("GET", "/api/config")[1]["features"]["standards_ai"]["on"] is False
    st, f = s.call("POST", "/api/features", {"standards_ai": True}); assert st == 200 and f["standards_ai"]["on"] is True
    assert s.call("POST", "/api/features", {"standards_ai": "yes"})[0] == 422
    ev = [e for e in s.call("GET", "/api/events?limit=50")[1] if e["action"] == "feature_changed"]; assert len(ev) == 1 and ev[0]["details"]["standards_ai"] == {"from": False, "to": True}
    from autoid_lite import server; again = server.App(s.app.cfg, tmp_path / "t.db"); assert again.feat_view()["standards_ai"]["on"] is True, "kept in the database"

@need_ff
def test_the_endpoint_is_gated_logs_only_counts_and_writes_nothing(tmp_path, monkeypatch):
    d = nitro(tmp_path, monkeypatch); f = d / "221126_WAR.mxf"; mxf(f, 6); monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; c = clip_on_nitro(s, f); url = "/api/clips/%d/standards" % c["id"]
    st, b = s.call("GET", url); assert st == 403 and "switched off" in b["detail"] and "Users > Features" in b["detail"]
    s.call("POST", "/api/features", {"standards_ai": True}); st, b = s.call("GET", url); assert st == 503 and "GROQ_API_KEY" in b["detail"]
    with_key(monkeypatch); cfg = s.call("GET", "/api/config")[1]; assert cfg["standards_key"] is True and KEY not in json.dumps(cfg)
    monkeypatch.setattr(clipsummary, "post_groq", lambda body, timeout=40, opener=None: {"choices": [{"message": {"content": reply(item(1, v="visible", note="blood on road"), item(2, d="blurred"), item(3))}}]}); before = tree(tmp_path)
    st, r = s.call("GET", url); assert st == 200 and r["counts"]["visible"] == 1 and r["counts"]["blurred"] == 1 and r["flags"][0]["verdict"] == "visible" and tree(tmp_path) == before
    with s.app.db.tx() as cur: ev = cur.q("SELECT details FROM events WHERE action='standards_check'")
    assert len(ev) == 1 and json.loads(ev[0]["details"]) == {"clip": c["display_id"], "frames": 3, "visible": 1, "blurred": 1, "unchecked": 0, "ai_error": False}, "who ran it and the counts; no notes, no pictures"
    assert "blood" not in ev[0]["details"] and KEY not in ev[0]["details"]
    assert s.call("GET", "/api/clips/99999/standards")[0] == 404
    s.cookie = None; assert s.call("GET", url)[0] == 401

# ------------------------------------------------------------------------------------------------ the page
def test_page_wiring_and_wording():
    for t in ('id="fstd"', 'featSave({standards_ai:$("#fstd").checked})', 'featOf("standards_ai").on', "🛡 Violence check (AI)", "/api/clips/\"+id+\"/standards", "function stdPanel(", "NOT BLURRED: ", "NOT CHECKED: look at this part yourself", "is NOT clearance", "an outside AI service", "Off until you switch it on", 'insRun(id,"d"', 'for(const k of ["q","f","s","d"])'): assert t in PAGE, t
    assert "GROQ_API_KEY" in PAGE and "gsk_" not in PAGE
    seg = PAGE[PAGE.index("const STDC="):PAGE.index("function insPanel(")]; assert "innerHTML" not in seg and "post(" not in seg and 'method:"POST"' not in seg and "clear\"" not in seg
    assert "Standards check (AI): nothing was flagged" in seg and "all clear" not in PAGE.lower() and "no problem" not in seg.lower()

def test_env_example_and_docs():
    t = (ROOT / "autoid.env.example").read_text(encoding="utf-8")
    for k in ("STANDARDS_NOTE", "STANDARDS_MAX_FRAMES", "STANDARDS_CATEGORIES", "STANDARDS_HEIGHT", "STANDARDS_MAX_SECONDS"): assert k in t, k
    d = (ROOT / "docs" / "CHANGES_v10160.md").read_text(encoding="utf-8"); assert "not clearance" in d.lower() and "NOT CHECKED" in d and "outside" in d

def _browser_ok():
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")): return False
    try: from playwright.sync_api import sync_playwright
    except ImportError: return False
    try:
        with sync_playwright() as pw: pw.chromium.launch().close()
    except Exception: return False
    return True

def test_the_whole_flow_in_a_real_browser(tmp_path, monkeypatch):
    if not _browser_ok(): pytest.skip("needs ffmpeg and playwright with a chromium browser")
    from playwright.sync_api import sync_playwright
    d = nitro(tmp_path, monkeypatch); f = d / "221126_WAR.mxf"; mxf(f, 4); with_key(monkeypatch)
    monkeypatch.setattr(clipsummary, "post_groq", lambda body, timeout=40, opener=None: {"choices": [{"message": {"content": reply(item(1, v="visible", note="man on the ground, blood"), item(2, d="blurred", note="mourner, face blurred"))}}]})
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; clip_on_nitro(s, f, "War story"); res = []
    def ok(cond, msg): res.append(bool(cond)); assert cond, msg
    with sync_playwright() as pw:
        br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 1500, "height": 950}); errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("dialog", lambda dl: dl.accept())
        pg.goto("http://127.0.0.1:%d/" % s.port); pg.fill("#u", "admin@x.io"); pg.fill("#p", "adminpass1"); pg.keyboard.press("Enter"); pg.wait_for_selector("#nav", timeout=15000); pg.wait_for_timeout(1200)
        pg.get_by_text("War story").first.click(); pg.wait_for_selector("text=Preview (low resolution)", timeout=10000)
        b0 = pg.locator("#detail button", has_text="Violence check"); ok(b0.count() == 1 and b0.is_disabled(), "v10.17.0: switched off: the Violence check button is shown, greyed out")
        pg.click("#navus"); pg.wait_for_selector("#fstd", state="visible"); ok(not pg.locator("#fstd").is_checked(), "the Features page shows it OFF by default"); pg.check("#fstd"); pg.wait_for_selector(".toast", timeout=8000)
        ok(s.call("GET", "/api/features")[1]["standards_ai"]["on"] is True, "the admin switch saved it")
        pg.click("#nav [data-tab=rundown]"); pg.wait_for_timeout(1500); pg.get_by_text("War story").first.click(); pg.wait_for_selector("text=Preview (low resolution)")
        b = pg.locator("#detail button", has_text="Violence check"); ok(b.count() == 1 and b.is_enabled(), "switched on and a key present: the button is there")
        b.click(); pg.wait_for_selector("text=Standards check (AI): 2 things to look at", timeout=60000)
        t = pg.locator("#detail .insp").inner_text(); ok("NOT BLURRED: violence" in t and "man on the ground, blood" in t and "AI says it is blurred: distressing scene" in t and "NOT clearance" in t and "outside service" in t, "the panel: " + t.replace("\n", " | ")[:300])
        ok(pg.evaluate("[...document.querySelectorAll('#detail .scf img')].length>=1 && [...document.querySelectorAll('#detail .scf img')].every(i=>i.naturalWidth>100)"), "flags carry their frame")
        ok(pg.locator("#detail .scf .v.bad").count() == 1 and pg.locator("#detail .scf .v.chk").count() == 1, "red for not blurred, amber for 'AI says blurred'")
        ok("gsk_" not in pg.content() and KEY not in pg.content(), "the key is nowhere in the page")
        pg.screenshot(path="/tmp/shots/standards.png"); ok(not errs, "no JavaScript error: %s" % errs[:2]); br.close()
