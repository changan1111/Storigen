"""v10.7.0: the safety rules around _U01 / _V01 (VERSION_SUFFIX=on): only the NEXT number makes a clip ID, bulletins that have aired are skipped, the order is the order things happened,
the desk is told (alerts, Ready feed), and the badge counts the clips really in the story (a replaced clip is marked, not counted)."""
import datetime as dt, sys, pathlib
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_server import Srv
from test_blaze_poll import media, clips, posts
from test_version_suffix import setup, attached_base, seen, in_story, dels, by_name

def srv_on(tmp_path, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1"); monkeypatch.setenv("VERSION_SUFFIX", "on")
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; return s

def mk(s, rundown, story): return s.call("POST", "/api/manual", {"rundown": rundown, "story": story})[1]
def starts(s, **t):
    with s.app.db.tx() as cur:
        for name, at in t.items(): cur.x("UPDATE rundowns SET start_at=? WHERE name=?", (at, name))
def iso(hours): return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).isoformat()
def match(s, name): return s.svc("GET", "/svc/match?name=" + name)

def test_1070_01_only_the_next_number_makes_a_clip_id_and_the_reason_is_given(tmp_path, monkeypatch):
    s = srv_on(tmp_path, monkeypatch); n = mk(s, "R", "Fire")["name_id"]
    st, body = match(s, n + "_U02"); assert st == 404 and "next update" in body["detail"] and "U01" in body["detail"], body
    assert match(s, n + "_V05")[0] == 404 and len(clips(s)) == 1
    assert match(s, n + "_u1")[0] == 200 and match(s, n + "_U03")[0] == 404 and match(s, n + "_U02")[0] == 200 and match(s, n + "_U03")[0] == 200
    assert match(s, n + "_V01")[0] == 200, "updates and added clips are counted separately"
    assert sorted(by_name(s)) == sorted([n, n + "_U01", n + "_U02", n + "_U03", n + "_V01"])

def test_1070_02_a_story_with_a_similar_name_does_not_count_for_the_other(tmp_path, monkeypatch):
    s = srv_on(tmp_path, monkeypatch); a = mk(s, "R", "Fire")["name_id"]; b = mk(s, "R", "Fire 2")["name_id"]; assert b == a + "_2"
    assert match(s, b + "_U01")[0] == 200 and match(s, a + "_U01")[0] == 200, "FIRE_2's update must not use up FIRE's number 1"

def test_1070_03_a_bulletin_that_has_aired_does_not_get_the_new_clip_id(tmp_path, monkeypatch):
    s = srv_on(tmp_path, monkeypatch); a = mk(s, "R1", "Fire"); mk(s, "R2", "Fire"); mk(s, "R3", "Fire"); starts(s, R1=iso(-3), R2=iso(1), R3=iso(2)); n = a["name_id"]
    assert match(s, n + "_U01")[0] == 200
    with s.app.db.tx() as cur: got = [x["r"] for x in cur.q("SELECT ru.name AS r FROM clip_ids c JOIN stories st ON st.id=c.story_id JOIN rundowns ru ON ru.id=st.rundown_id WHERE c.version=1001 ORDER BY ru.name")]
    assert got == ["R2", "R3"], got

def test_1070_04_when_every_bulletin_has_aired_the_newest_one_takes_it(tmp_path, monkeypatch):
    s = srv_on(tmp_path, monkeypatch); a = mk(s, "R1", "Fire"); mk(s, "R2", "Fire"); starts(s, R1=iso(-5), R2=iso(-3))
    assert match(s, a["name_id"] + "_V01")[0] == 200
    with s.app.db.tx() as cur: got = [x["r"] for x in cur.q("SELECT ru.name AS r FROM clip_ids c JOIN stories st ON st.id=c.story_id JOIN rundowns ru ON ru.id=st.rundown_id WHERE c.version=2001")]
    assert got == ["R2"], got

def test_1070_05_the_clip_lists_are_in_the_order_things_happened(tmp_path, monkeypatch):
    s = srv_on(tmp_path, monkeypatch); n = mk(s, "R", "Fire")["name_id"]
    for x in ("_V01", "_U01", "_V02"): assert match(s, n + x)[0] == 200
    want = [n, n + "_V01", n + "_U01", n + "_V02"]      # not every update before every added clip
    assert [x["name_id"] for x in s.svc("GET", "/svc/clips")[1]] == want and [x["name_id"] for x in s.call("GET", "/api/clips")[1]["clips"]] == want

def test_1070_06_the_desk_is_told_when_a_clip_id_is_made_from_a_file_name(tmp_path, monkeypatch):
    s = srv_on(tmp_path, monkeypatch); n = mk(s, "R", "Fire")["name_id"]; got = []; monkeypatch.setattr(s.app, "alert", lambda t: got.append(t))
    match(s, n + "_U01"); match(s, n + "_V01"); match(s, n + "_U01")
    assert len(got) == 2 and "UPDATE" in got[0] and n + "_U01" in got[0] and "NEW CLIP" in got[1] and n + "_V01" in got[1], got

def test_1070_07_the_ready_feed_says_update_or_added(tmp_path, monkeypatch):
    s = srv_on(tmp_path, monkeypatch); n = mk(s, "R", "Fire")["name_id"]
    for i, x in enumerate(("_U01", "_V01")): m = match(s, n + x)[1]; s.svc("POST", "/svc/media", {"display_id": m["display_id"], "media_id": str(2000 + i)})
    items = {x["name_id"]: x for x in s.call("GET", "/api/feed")[1]["items"]}
    assert (items[n + "_U01"]["label"], items[n + "_U01"]["kind"]) == ("U01", "update") and (items[n + "_V01"]["label"], items[n + "_V01"]["kind"]) == ("V01", "added")

def test_1070_08_an_added_clip_tells_the_desk_the_story_has_several_clips(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = attached_base(s, f, p, base)["name_id"]; got = []; monkeypatch.setattr(s.app, "alert", lambda t: got.append(t))
    seen(s, n + "_V01"); f.medias.append(media(1002, n + "_V01.mxf")); p.cycle()
    assert len(posts(f)) == 2 and any("Multiple clips" in x and "2 clips" in x and n + "_V01" in x for x in got), got
    assert not any("UPDATED" in x for x in got)

def test_1070_09_an_update_marks_the_old_clip_replaced_and_tells_the_desk(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = attached_base(s, f, p, base)["name_id"]; got = []; monkeypatch.setattr(s.app, "alert", lambda t: got.append(t))
    seen(s, n + "_V01"); f.medias.append(media(1002, n + "_V01.mxf")); p.cycle()
    seen(s, n + "_U01"); f.medias.append(media(1003, n + "_U01.mxf")); p.cycle()
    assert sorted(in_story(f)) == sorted([n + "_V01.mxf", n + "_U01.mxf"]) and len(dels(f)) == 1
    rows = {x["name_id"]: x for x in s.svc("GET", "/svc/clips")[1]}; s.login()
    ui = {x["name_id"]: x for x in s.call("GET", "/api/clips")[1]["clips"]}
    assert ui[n]["replaced_label"] == "U01" and ui[n]["replaced_at"] and not ui[n + "_U01"]["replaced_at"] and not ui[n + "_V01"]["replaced_at"]
    assert ui[n + "_U01"]["story_clips"] == 2, "the update and the added clip are in the story; the replaced plain clip is not counted"
    assert any("UPDATED" in x and n + "_U01" in x for x in got), got
    hist = s.call("GET", "/api/clips/%d/history" % ui[n]["id"])[1]["story_clips"]; assert [(x["label"], x["replaced"]) for x in hist] == [("BASE", True), ("V01", False), ("U01", False)]
    p.cycle(); p.cycle(); assert len(posts(f)) == 3 and len(dels(f)) == 1, "nothing is repeated"

def test_1070_10_the_replaced_call_is_checked(tmp_path, monkeypatch):
    s = srv_on(tmp_path, monkeypatch); a = mk(s, "R", "Fire"); b = mk(s, "R", "Other")
    assert s.svc("POST", "/svc/replaced", {"display_id": a["display_id"], "replaced": [b["display_id"]]})[1]["marked"] == 0, "a clip of ANOTHER story is never marked"
    assert s.svc("POST", "/svc/replaced", {"display_id": a["display_id"], "replaced": [a["display_id"]]})[1]["marked"] == 0, "a clip never replaces itself"
    assert s.svc("POST", "/svc/replaced", {"display_id": "nope", "replaced": []})[0] == 404 and s.svc("POST", "/svc/replaced", {"display_id": a["display_id"], "replaced": "x"})[0] == 422
