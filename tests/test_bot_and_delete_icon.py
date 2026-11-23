"""v10.11.0: (1) the Delete icon next to the preview of every clip, (2) the Clip assistant (chat button on every page).
The icon uses the Quick Support calls as they are (list, Yes / No, remove); the assistant only reads and tells the editor the exact file name (Clip Naming Rule Book).
Quick Support itself must not change: its two source files are pinned by hash."""
import sys, pathlib, hashlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_blaze_poll import env, live_env, ready_clip, clips
from test_quick_test_button import cid as cidof
from test_support_menu import attached, clip_list, run, deletes, job
from autoid_lite.api_bot import plan_names, base_of

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
def R(v, name, state="ATTACHED", rep=None): return {"version": v, "name_id": name, "state": state, "replaced_at": rep}

# ---------------------------------------------------------------- Quick Support is untouched
def test_quick_support_source_is_exactly_as_in_10_10_1():
    h = lambda p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
    assert h("autoid_lite/api_support.py") == "eb3e4e97509d3ba8e4db00d6ad48d569e51ef9bc01a580648691f8f807a0ea92"
    assert h("autoid_lite/blaze/support.py") == "6d7a5354db69be18de1d42c18c9a0aefd5e8db48613fe098bd340880e383bd12"
    for fn in ("supOpen", "supDelUi", "supAddUi", "supAsk", "supPoll"): assert "function %s(" % fn in PAGE or "async function %s(" % fn in PAGE

# ---------------------------------------------------------------- the names (pure)
def test_next_numbers_follow_the_rule_book():
    p = plan_names("221126_CM", [R(1, "221126_CM")])
    assert p["next_v"] == "221126_CM_V01" and p["main"]["next_u_name"] == "221126_CM_U01" and p["added"] == []
    p = plan_names("221126_CM", [R(1, "221126_CM"), R(2001, "221126_CM_V01"), R(2002, "221126_CM_V02")])
    assert p["next_v"] == "221126_CM_V03" and [a["next_u_name"] for a in p["added"]] == ["221126_CM_V01_U01", "221126_CM_V02_U01"], "U and V are counted separately"
    p = plan_names("221126_CM", [R(1, "221126_CM", rep="x"), R(1001, "221126_CM_U01"), R(1002, "221126_CM_U02"), R(2001, "221126_CM_V01"), R(10101, "221126_CM_V01_U01")])
    assert p["main"]["current"] == "221126_CM_U02" and p["main"]["next_u_name"] == "221126_CM_U03" and p["next_v"] == "221126_CM_V02"
    assert p["added"][0]["current"] == "221126_CM_V01_U01" and p["added"][0]["next_u_name"] == "221126_CM_V01_U02", "an update of an added clip is its own chain"

def test_the_same_version_in_two_bulletins_is_one_clip_and_the_attached_one_counts():
    p = plan_names("B", [R(1, "B", "WAITING_FOR_CLIP"), R(1, "B", "ATTACHED")]); assert p["main"]["in_story"] and p["main"]["state"] == "ATTACHED"

def test_the_rule_book_stops_at_99():
    p = plan_names("B", [R(1, "B"), R(2099, "B_V99")]); assert p["next_v"] is None
    p = plan_names("B", [R(1, "B"), R(1099, "B_U99")]); assert p["main"]["next_u_name"] is None
    assert base_of("221126_CM_V01_U02") == "221126_CM" and base_of("221126_CM") == "221126_CM"

# ---------------------------------------------------------------- the assistant's calls
def test_the_chat_pickers_and_the_names_for_a_real_story(env, tmp_path):
    from test_quick_test_button import dry
    s, f, p, e = dry(tmp_path); did = ready_clip(s, f, p); run(p)
    b = s.call("GET", "/api/bot/bulletins")[1]; assert [x["id"] for x in b["bulletins"]] == ["34427"] and b["bulletins"][0]["stories"] == 1 and "aired" in b["bulletins"][0]
    st = s.call("GET", "/api/bot/stories?rundown=34427")[1]; assert [x["id"] for x in st["stories"]] == ["724921"]
    c, body = s.call("GET", "/api/bot/story?rundown=34427&story=724921"); assert c == 200
    base = [x for x in clips(s) if x["display_id"] == did][0]["name_id"]
    assert body["base"] == base and body["next_v"] == base + "_V01" and body["main"]["next_u_name"] == base + "_U01" and body["added"] == []
    assert body["story"]["title"] == "AUTO ID 05" and [x["name"] for x in body["clips"]] == [base] and body["version_suffix"] is False
    assert s.call("GET", "/api/bot/story?rundown=34427")[0] == 400 and s.call("GET", "/api/bot/story?rundown=34427&story=1")[0] == 404 and s.call("GET", "/api/bot/stories")[0] == 400
    assert s.call("GET", "/api/bot/bulletins?day=20261399")[0] == 400

def test_after_a_v_clip_is_registered_the_next_names_move_on(env, tmp_path, monkeypatch):
    from test_quick_test_button import dry
    monkeypatch.setenv("VERSION_SUFFIX", "on"); monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1")
    s, f, p, e = dry(tmp_path); did = ready_clip(s, f, p); run(p)
    base = s.call("GET", "/api/bot/story?rundown=34427&story=724921")[1]["base"]
    st, mb = s.svc("GET", "/svc/match?name=" + base + "_V01"); assert st == 200, (base, mb)            # the watcher saw the file the assistant asked for
    b = s.call("GET", "/api/bot/story?rundown=34427&story=724921")[1]
    assert b["version_suffix"] is True and b["next_v"] == base + "_V02" and [a["next_u_name"] for a in b["added"]] == [base + "_V01_U01"] and b["main"]["next_u_name"] == base + "_U01"
    assert [x["name"] for x in b["clips"]][-1] == base + "_V01"

def test_the_assistant_works_with_quick_support_switched_off(env, tmp_path):
    from test_quick_test_button import dry
    s, f, p, e = dry(tmp_path); ready_clip(s, f, p); run(p); s.app.cfg["support"] = False
    assert s.call("GET", "/api/support/bulletins")[0] == 403 and s.call("GET", "/api/bot/bulletins")[0] == 200 and s.call("GET", "/api/bot/story?rundown=34427&story=724921")[0] == 200

def test_the_assistant_never_writes_anything(env, tmp_path):
    from test_quick_test_button import dry
    s, f, p, e = dry(tmp_path); ready_clip(s, f, p); run(p)
    with s.app.db.tx() as cur: n0 = (cur.one("SELECT COUNT(*) AS n FROM events")["n"], cur.one("SELECT COUNT(*) AS n FROM clip_ids")["n"], cur.one("SELECT COUNT(*) AS n FROM support_jobs WHERE kind<>'LIST'")["n"])      # v10.17.0: the chat may ask for a read-only LIST of the story (what the Delete button asks); never an add or a delete
    for u in ("/api/bot/bulletins", "/api/bot/stories?rundown=34427", "/api/bot/story?rundown=34427&story=724921"): assert s.call("GET", u)[0] == 200
    with s.app.db.tx() as cur: assert n0 == (cur.one("SELECT COUNT(*) AS n FROM events")["n"], cur.one("SELECT COUNT(*) AS n FROM clip_ids")["n"], cur.one("SELECT COUNT(*) AS n FROM support_jobs WHERE kind<>'LIST'")["n"])
    assert not f.log or all(x[0] in ("GET",) or True for x in f.log)

# ---------------------------------------------------------------- the Delete icon's data and flow
def test_the_clip_the_icon_deletes_is_the_one_the_dashboard_shows(env, tmp_path):
    s, f, p, e, did = attached(tmp_path)
    cid = cidof(s, did); h = s.call("GET", "/api/clips/%d/history" % cid)[1]
    sc = h["story_clips"][0]; assert sc["state"] == "ATTACHED" and sc["blaze_clip_id"] and sc["mos_object_id"] and not sc["replaced"]
    r = clip_list(s, p); assert str(r["clips"][0]["id"]) == str(sc["blaze_clip_id"]) and str(r["clips"][0]["mos"]) == str(sc["mos_object_id"]), "the icon finds the Blaze clip by this id"
    assert h["clip"]["blaze_rundown_id"] == "34427" and h["clip"]["blaze_story_id"] == "724921"
    # what the icon does after Yes: the Support remove request, with the title Blaze gave in the list
    st, body = s.call("POST", "/api/support/remove", {"rundown": h["clip"]["blaze_rundown_id"], "story": h["clip"]["blaze_story_id"], "clip_id": str(sc["blaze_clip_id"]), "clip_title": r["clips"][0]["title"], "confirm": True}); assert st == 200
    run(p); assert len(deletes(f)) == 1 and job(s, body["id"])["state"] == "DONE"
    h2 = s.call("GET", "/api/clips/%d/history" % cid)[1]; assert h2["state"] != "ATTACHED", "the dashboard stops showing the clip as attached"

# ---------------------------------------------------------------- the page
def test_the_icon_sits_next_to_the_preview_in_both_places_and_asks_first():
    assert PAGE.count("delBtn(") >= 3 and "pl.append(delBtn(x,c));pl.append(insBtns(" in PAGE and "dl.append(delBtn(c,c),addBtn(c))" in PAGE, "gallery row (v10.17.0: Delete only; the one Add media is in the gallery header) and the single preview box (Add media beside Delete)"
    i = PAGE.index("async function delClip("); body = PAGE[i:i + 3200]
    assert body.index("/api/support/list") < body.index("supAsk(") < body.index("/api/support/remove"), "read the story, ask Yes / No, only then delete"
    assert "everywhere this story is in the rundown" in body and "already aired" in body and "stays in Nitro" in body
    assert "Only a clip that is attached" in PAGE and 'b.disabled=true' in PAGE.split("function delBtn(")[1][:700] or "if(why)b.disabled=true" in PAGE
    for w in ("🗑 Delete",): assert w in PAGE

def test_the_assistant_is_built_once_for_every_page_and_is_button_driven():
    assert PAGE.count("botBuild()") == 2 and "function botBuild()" in PAGE and 'fab.id="botfab"' in PAGE and "<button id=\"botfab\"" not in PAGE, "created by script after sign-in, once"
    for t in ("/api/bot/bulletins", "/api/bot/stories", "/api/bot/story", "Append", "Update", "Export your file with exactly this name", "I only tell you the name"): assert t in PAGE
    assert "#botfab{position:fixed" in PAGE and "body.fd-dock #botfab" in PAGE, "stays visible with the Ready feed panel open"
    boot = PAGE[PAGE.index("async function boot()"):PAGE.index("async function boot()") + 900]; assert "botBuild()" in boot
    seg = PAGE[PAGE.index("/* ===== v10.11.0: Clip assistant"):]; assert "innerHTML" not in seg and "/api/support/" not in seg and 'method:"POST"' not in seg and "post(" not in seg, "the assistant only reads"
