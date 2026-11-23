"""v10.15.0: Missing-clip board (stories with no clip, countdown to the bulletin, red under N minutes, Add media one click away) and Bulletin smoke test (pick a bulletin, Quick test, bar graph),
both switched on / off by an admin from the page (stored in the database, not autoid.env). Both only read the registry."""
import sys, pathlib, time, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from test_server import Srv

ROOT = pathlib.Path(__file__).resolve().parents[1]
def page(): return (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
def at(mins): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + mins * 60))

def bulletin(s, rid, name, start_mins, titles, **kw):
    st = [{"blaze_story_id": "%s%02d" % (rid, i), "slug": t, "slug_id": "9%s%02d" % (rid, i), "position": i, "story_title": t} for i, t in enumerate(titles, 1)]
    body = {"blaze_rundown_id": rid, "rundown_name": name, "stories": st}
    if start_mins is not None: body["rundown_start"] = at(start_mins)
    assert s.svc("POST", "/svc/rundowns/sync", body)[0] == 200
def setstate(s, rid, pos, state, **cols):
    with s.app.db.tx() as cur:
        sid = cur.one("SELECT s.id FROM stories s JOIN rundowns r ON r.id=s.rundown_id WHERE r.blaze_rundown_id=? AND s.blaze_story_id=?", (rid, "%s%02d" % (rid, pos)))["id"]
        sets = ", ".join("%s=?" % k for k in cols); cur.x("UPDATE clip_ids SET state=?%s WHERE story_id=?" % ((", " + sets) if sets else ""), [state] + list(cols.values()) + [sid])
def board(s, q=""): st, r = s.call("GET", "/api/missing" + q); assert st == 200, r; return r
def titles(b): return [x["title"] for x in b["stories"]]

@pytest.fixture
def s(tmp_path):
    x = Srv(tmp_path, "story_id"); assert x.login()[0] == 200; return x
@pytest.fixture
def ed(tmp_path):
    x = Srv(tmp_path, "story_id"); assert x.login()[0] == 200
    assert x.call("POST", "/api/users", {"email": "ed@x.io", "password": "editorpass1", "role": "editor", "valid_upto": "2099-01-01"})[0] in (200, 201)
    return x

# ------------------------------------------------------------------ the switches (database, admin only)
def test_both_features_are_on_until_an_admin_switches_them_off_and_the_page_is_told(s):
    st, f = s.call("GET", "/api/features"); assert st == 200 and f["missing_board"]["on"] is True and f["missing_board"]["minutes"] == 20 and f["smoke_test"]["on"] is True
    assert s.call("GET", "/api/config")[1]["features"]["missing_board"]["on"] is True

def test_an_admin_switches_a_feature_off_and_on_from_the_page_and_it_is_logged_and_kept(s, tmp_path):
    st, f = s.call("POST", "/api/features", {"missing_board": False}); assert st == 200 and f["missing_board"]["on"] is False and f["smoke_test"]["on"] is True and "missing" not in f["missing_board"]
    assert s.call("GET", "/api/missing")[0] == 403 and "switched off" in s.call("GET", "/api/missing")[1]["detail"] and s.call("GET", "/api/smoke")[0] == 200
    assert s.call("POST", "/api/features", {"smoke_test": False})[0] == 200 and s.call("GET", "/api/smoke")[0] == 403
    ev = [e for e in s.call("GET", "/api/events?limit=50")[1] if e["action"] == "feature_changed"]
    assert len(ev) == 2 and ev[0]["actor"] == "admin@x.io" and ev[1]["details"]["missing_board"] == {"from": True, "to": False}
    from autoid_lite import server                                                                      # a restart: the switch is in the database, nothing to read from the environment
    again = server.App(s.app.cfg, tmp_path / "t.db"); assert again.feat_view()["missing_board"]["on"] is False and again.feat_view()["smoke_test"]["on"] is False
    assert s.call("POST", "/api/features", {"missing_board": True, "smoke_test": True})[0] == 200 and s.call("GET", "/api/missing")[0] == 200

def test_setting_a_switch_to_what_it_already_is_writes_nothing_to_the_log(s):
    s.call("POST", "/api/features", {"smoke_test": True}); assert not [e for e in s.call("GET", "/api/events?limit=50")[1] if e["action"] == "feature_changed"]

def test_only_an_admin_may_change_the_switches_and_bad_input_is_refused(s, ed):
    assert ed.login("ed@x.io", "editorpass1")[0] == 200
    assert ed.call("GET", "/api/features")[0] == 200 and ed.call("POST", "/api/features", {"missing_board": False})[0] == 403
    assert s.call("POST", "/api/features", {})[0] == 400 and s.call("POST", "/api/features", {"nothing": 1})[0] == 400
    for bad in ("yes", 1, None, "false"): assert s.call("POST", "/api/features", {"missing_board": bad})[0] == 422, bad
    for bad in (0, 241, -5, "x", True, 2.5, [20], None): assert s.call("POST", "/api/features", {"missing_minutes": bad})[0] == 422, bad
    assert s.call("GET", "/api/features")[1]["missing_board"]["minutes"] == 20, "a refused change leaves everything as it was"
    assert s.call("POST", "/api/features", {"missing_minutes": "30"})[1]["missing_board"]["minutes"] == 30 and s.call("POST", "/api/features", {"missing_minutes": 240})[0] == 200
    s.cookie = None; assert s.call("GET", "/api/features")[0] == 401 and s.call("GET", "/api/missing")[0] == 401 and s.call("GET", "/api/smoke")[0] == 401

def test_a_damaged_stored_value_never_breaks_the_page(s):
    with s.app.db.tx() as cur: cur.x("INSERT INTO settings(key,value) VALUES('feature.missing_board.minutes','abc'),('feature.missing_board','garbage')")
    f = s.call("GET", "/api/features")[1]; assert f["missing_board"]["minutes"] == 20 and f["missing_board"]["on"] is True

# ------------------------------------------------------------------ the board
def test_the_board_lists_only_stories_without_a_clip_soonest_bulletin_first(s):
    bulletin(s, "20", "Late Bulletin", 180, ["L1", "L2"]); bulletin(s, "10", "Soon Bulletin", 15, ["A", "B", "C"])
    setstate(s, "10", 2, "ATTACHED", attached_at="2026-01-01T00:00:00Z")
    b = board(s); assert [x["name"] for x in b["bulletins"]] == ["Soon Bulletin", "Late Bulletin"]
    soon = b["bulletins"][0]; assert titles(soon) == ["A", "C"] and soon["total"] == 3 and soon["missing"] == 2 and soon["stories"][0]["rundown"] == "10" and soon["stories"][0]["id"] == "1001"
    assert b["missing"] == 4 and b["minutes"] == 20 and abs(b["now_ms"] - time.time() * 1000) < 5000

def test_a_bulletin_under_the_limit_is_red_and_the_limit_is_the_admins_to_change(s):
    bulletin(s, "10", "In 10 min", 10, ["A"]); bulletin(s, "11", "In 19 min", 19, ["B"]); bulletin(s, "12", "In 25 min", 25, ["C"]); bulletin(s, "13", "In 90 min", 90, ["D"])
    red = lambda: {x["name"]: x["red"] for x in board(s)["bulletins"]}
    assert red() == {"In 10 min": True, "In 19 min": True, "In 25 min": False, "In 90 min": False} and board(s)["red"] == 2
    s.call("POST", "/api/features", {"missing_minutes": 30}); assert red()["In 25 min"] is True and red()["In 90 min"] is False
    s.call("POST", "/api/features", {"missing_minutes": 5}); assert red() == {"In 10 min": False, "In 19 min": False, "In 25 min": False, "In 90 min": False} and board(s)["red"] == 0

def test_a_bulletin_that_is_on_air_is_red_one_that_has_aired_is_left_out_and_never_red(s):
    bulletin(s, "10", "On air since 5 min", -5, ["A"]); bulletin(s, "11", "Aired 3 h ago", -180, ["B"]); bulletin(s, "12", "No time", None, ["C"])
    b = board(s); assert [x["name"] for x in b["bulletins"]] == ["On air since 5 min", "No time"]
    assert b["bulletins"][0]["red"] is True and b["bulletins"][0]["minutes_left"] < 0 and b["bulletins"][1]["red"] is False and b["bulletins"][1]["start_ms"] is None, "no start time: listed last, never red"
    b = board(s, "?aired=1"); assert [x["name"] for x in b["bulletins"]] == ["Aired 3 h ago", "On air since 5 min", "No time"] and b["bulletins"][0]["aired"] is True and b["bulletins"][0]["red"] is False
    assert b["missing"] == 2 and b["red"] == 1, "the counts (and the menu badge) never include a bulletin that has aired"

def test_what_counts_as_having_a_clip(s):
    bulletin(s, "10", "B", 10, ["has clip", "replaced only", "removed in blaze", "no file", "converting", "file in blaze", "attach sent", "needs desk", "deleted by support"])
    setstate(s, "10", 1, "ATTACHED"); setstate(s, "10", 2, "ATTACHED", replaced_at="2026-01-01T00:00:00Z")
    setstate(s, "10", 5, "EXPORTING"); setstate(s, "10", 6, "ON_NITRO", media_found_at="2026-01-01T00:00:00Z"); setstate(s, "10", 7, "ATTACH_SUBMITTED"); setstate(s, "10", 8, "NEEDS_DESK"); setstate(s, "10", 9, "NEEDS_DESK")
    with s.app.db.tx() as cur: cur.x("UPDATE stories SET deleted=1 WHERE blaze_story_id='1003'")
    got = {x["title"]: x["status"] for x in board(s)["bulletins"][0]["stories"]}
    assert got == {"replaced only": "NO_FILE", "no file": "NO_FILE", "converting": "EXPORTING", "file in blaze": "FILE_READY", "attach sent": "ATTACH_SENT", "needs desk": "NEEDS_DESK", "deleted by support": "NEEDS_DESK"}
    assert [x["status_text"] for x in board(s)["bulletins"][0]["stories"]][2:5] == ["File seen, still converting", "File is in Blaze, not attached yet", "Attach sent, being checked"]

def test_a_story_with_several_clips_has_a_clip_when_one_is_attached(s):
    bulletin(s, "10", "B", 10, ["two clips"]); setstate(s, "10", 1, "ATTACHED")
    with s.app.db.tx() as cur:
        c = cur.one("SELECT * FROM clip_ids LIMIT 1"); cur.insert("INSERT INTO clip_ids(display_id,day,seq,story_id,version,state,created_at,name_id) VALUES(?,?,?,?,?,?,?,?)", (c["display_id"] + "V", c["day"], c["seq"], c["story_id"], 2, "WAITING_FOR_CLIP", c["created_at"], "X_V2"))
    assert board(s)["bulletins"] == [] and board(s)["missing"] == 0

def test_typed_by_hand_stories_are_not_on_the_board_there_is_nothing_to_attach_to_in_blaze(tmp_path):
    ph = Srv(tmp_path, "placeholder"); assert ph.login()[0] == 200
    assert ph.call("POST", "/api/manual", {"rundown": "R1", "story": "typed story"})[0] == 200
    assert board(ph)["bulletins"] == [] and ph.call("GET", "/api/smoke")[1]["bulletins"] == []

def test_a_story_someone_already_asked_media_for_says_so(s):
    bulletin(s, "10", "B", 10, ["A", "B"])
    with s.app.db.tx() as cur: cur.x("INSERT INTO support_jobs(kind,state,blaze_rundown_id,blaze_story_id,story) VALUES('ADD','QUEUED','10','1001','A'),('ADD','DONE','10','1002','B')")
    assert [(x["title"], x["add_queued"]) for x in board(s)["bulletins"][0]["stories"]] == [("A", True), ("B", False)]

def test_the_menu_badge_numbers_come_with_the_switches_and_bad_days_are_refused(s):
    bulletin(s, "10", "Soon", 10, ["A", "B"]); bulletin(s, "11", "Later", 120, ["C"])
    m = s.call("GET", "/api/features")[1]["missing_board"]; assert m["missing"] == 3 and m["red"] == 2
    for bad in ("2026", "20261340", "abc"): assert s.call("GET", "/api/missing?day=" + bad)[0] == 400 and s.call("GET", "/api/smoke?day=" + bad)[0] == 400
    assert board(s, "?day=20000101")["bulletins"] == []

# ------------------------------------------------------------------ the smoke test
def test_the_smoke_test_lists_the_days_bulletins_for_the_picker(s):
    bulletin(s, "11", "Later", 120, ["C"]); bulletin(s, "10", "Soon", 10, ["A", "B"])
    l = s.call("GET", "/api/smoke")[1]; assert [(x["id"], x["total"]) for x in l["bulletins"]] == [("10", 2), ("11", 1)] and l["bulletins"][0]["start_ms"] and "stories" not in l["bulletins"][0]

def test_the_quick_test_counts_the_stories_with_a_clip(s):
    bulletin(s, "10", "Soon", 10, ["A", "B", "C", "D"]); setstate(s, "10", 1, "ATTACHED"); setstate(s, "10", 3, "ATTACHED"); setstate(s, "10", 4, "ON_NITRO", media_found_at="2026-01-01T00:00:00Z")
    st, r = s.call("GET", "/api/smoke?rundown=10"); assert st == 200 and (r["total"], r["attached"], r["missing"], r["ok"]) == (4, 2, 2, False)
    assert [(x["title"], x["status"]) for x in r["stories"]] == [("B", "NO_FILE"), ("D", "FILE_READY")] and r["bulletin"]["name"] == "Soon" and r["poller_age_s"] is None and r["stale_s"] > 0
    setstate(s, "10", 2, "ATTACHED"); setstate(s, "10", 4, "ATTACHED"); r = s.call("GET", "/api/smoke?rundown=10")[1]; assert (r["total"], r["attached"], r["ok"], r["stories"]) == (4, 4, True, [])

def test_the_quick_test_only_counts_the_chosen_bulletin_and_says_so_for_an_unknown_one(s):
    bulletin(s, "10", "One", 10, ["A", "B"]); bulletin(s, "11", "Two", 20, ["C"]); setstate(s, "11", 1, "ATTACHED")
    assert s.call("GET", "/api/smoke?rundown=10")[1]["total"] == 2 and s.call("GET", "/api/smoke?rundown=11")[1]["ok"] is True
    assert s.call("GET", "/api/smoke?rundown=999")[0] == 404

def test_the_quick_test_tells_how_fresh_the_poller_is(s):
    bulletin(s, "10", "One", 10, ["A"])
    s.svc("POST", "/svc/heartbeat", {"component": "blaze_poll", "detail": {}}); r = s.call("GET", "/api/smoke?rundown=10")[1]; assert r["poller_age_s"] is not None and r["poller_age_s"] < 5

# ------------------------------------------------------------------ safety: read-only, and the page
def test_neither_view_writes_anything_or_asks_blaze(s):
    bulletin(s, "10", "One", 10, ["A", "B"])
    with s.app.db.tx() as cur: before = (cur.one("SELECT COUNT(*) n FROM events")["n"], cur.one("SELECT COUNT(*) n FROM support_jobs")["n"], cur.one("SELECT COUNT(*) n FROM clip_ids")["n"])
    for _ in range(3): board(s); s.call("GET", "/api/smoke"); s.call("GET", "/api/smoke?rundown=10"); s.call("GET", "/api/features")
    with s.app.db.tx() as cur: assert before == (cur.one("SELECT COUNT(*) n FROM events")["n"], cur.one("SELECT COUNT(*) n FROM support_jobs")["n"], cur.one("SELECT COUNT(*) n FROM clip_ids")["n"])
    src = (ROOT / "autoid_lite" / "api_features.py").read_text(encoding="utf-8")
    assert "BlazeClient" not in src and "check_call" not in src and "import requests" not in src and "urllib" not in src

def test_the_page_has_both_menu_items_panels_and_the_switches_and_no_env_setting_is_needed():
    t = page()
    for k in ('id="navmiss"', 'data-tab="missing"', 'id="navsmoke"', 'data-tab="smoke"', 'id="missbox"', 'id="misslist"', 'id="smokebox"', 'id="smokesel"', 'id="smokego"', 'id="featbox"', 'id="fmiss"', 'id="fmin"', 'id="fsmoke"', "function missLoad", "function smokeGo", "function featApply", "/api/features", "/api/missing", "/api/smoke", "missAddBtn", "addBtn({blaze_rundown_id:s.rundown"): assert k in t, k
    assert t.index('id="featbox"') < t.index("<h2>Users</h2>") and t.index('id="navsup"') < t.index('id="navmiss"') < t.index('id="navins"')
    assert 'pgTab==="missing"&&featOf("missing_board").on' in t and 'pgTab==="smoke"&&featOf("smoke_test").on' in t
    env = (ROOT / "autoid.env.example").read_text(encoding="utf-8")
    assert "MISSING_BOARD" not in env and "SMOKE_TEST" not in env
    seg = page()[page().index("/* ===== v10.15.0"):page().index("/* ===== v10.11.0: Delete icon")]; assert "localStorage" not in seg and "innerHTML" not in seg      # the helpers only; text is set with textContent

# ------------------------------------------------------------------ the real page against a real server, in a headless DOM
def test_the_board_the_smoke_test_and_the_switches_in_a_headless_browser(ed):
    import os, shutil, subprocess
    node = shutil.which("node"); js = ROOT / "tools" / "dev" / "check_missing_smoke.js"
    if not node: pytest.skip("node is not installed (developer check only)")
    env = dict(os.environ); env["NODE_PATH"] = os.pathsep.join(p for p in [str(ROOT / "tools" / "dev" / "node_modules"), env.get("NODE_PATH", "")] if p)
    if subprocess.run([node, "-e", "require('jsdom')"], env=env, capture_output=True).returncode: pytest.skip("jsdom is not installed: cd tools/dev && npm install jsdom")
    bulletin(ed, "10", "Soon Bulletin", 12, ["Story A", "Story B", "Story C"]); setstate(ed, "10", 1, "ATTACHED")
    bulletin(ed, "11", "Later Bulletin", 118, ["Story D", "Story E"]); bulletin(ed, "12", "Old Bulletin", -200, ["Story F"])
    r = subprocess.run([node, str(js), str(ed.port), "admin@x.io", "adminpass1", "ed@x.io", "editorpass1"], env=env, capture_output=True, text=True, timeout=240)
    assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, r.stdout[-4000:] + r.stderr[-800:]
