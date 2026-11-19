"""v10.5.0, VERSION_SUFFIX=on: a file name ending _U01 / _U02 UPDATES the story's clip (attach, read back, then remove the old one); _V01 / _V02 ADDS a clip next to the ones already there.
The clip ID for such a file is created the first time the file is seen: nobody clicks +Version. With the switch off (the default) nothing changes."""
import sys, pathlib
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_blaze_poll import slug, media, clips, posts, bp, set_state, watch_lines, live_env
from autoid_lite import watcher as w, ids
from autoid_lite.blaze import keys

def setup(tmp_path, monkeypatch, on=True, **extra):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1"); monkeypatch.setenv("VERSION_SUFFIX", "on" if on else "off")
    s, f, p, e = live_env(tmp_path, **extra); f.slugs = [slug(724921, "FIRE", 14, 20)]; p.cycle(); base = clips(s)[0]; return s, f, p, base

def attached_base(s, f, p, base):
    set_state(s, base["display_id"], "ON_NITRO"); f.medias = [media(1001, base["name_id"] + ".mxf")]; p.cycle()
    assert [r["state"] for r in clips(s)] == ["ATTACHED"] and len(posts(f)) == 1; return base

def seen(s, name):
    """what the watcher does with a new file: ask the registry for its name (this creates the clip ID), then report it on Nitro"""
    st, m = s.svc("GET", "/svc/match?name=" + name); assert st == 200, (st, m)
    s.svc("POST", "/svc/files", {"display_id": m["display_id"], "state": "ON_NITRO"}); return m

def in_story(f, sid="724921"): return [t for _, t in f.story_clips.get(sid, [])]
def dels(f): return [x for x in f.log if x[0] == "DELETE"]
def by_name(s): return {r["name_id"]: r for r in clips(s)}

def test_1050_01_the_ending_is_read_by_the_watcher_and_the_poller_only_when_the_switch_is_on(monkeypatch):
    monkeypatch.setenv("VERSION_SUFFIX", "on"); w.SUFFIX_ON = True
    try:
        assert w.parse_name("111126_FIRE_U02.mxf") == ("NAME", "111126_FIRE_U02", 1002, None) and w.parse_name("111126 fire v01.mxf") == ("NAME", "111126_FIRE_V01", 2001, None) and w.parse_name("111126_FIRE.mxf")[2] == 1
        assert keys.media_key("111126_FIRE_U02.mxf") == ("111126_FIRE", 1002) and keys.media_key("111126_FIRE_V01.mxf") == ("111126_FIRE", 2001) and keys.media_key("111126_FIRE.mxf") == ("111126_FIRE", 1)
        assert keys.clip_key("111126_FIRE_U02", 1002) == keys.media_key("111126_fire u2.mxf") and ids.vlabel(1002) == "U02" and ids.vlabel(2001) == "V01" and ids.vlabel(1) == "1"
    finally: w.SUFFIX_ON = False
    monkeypatch.setenv("VERSION_SUFFIX", "off")
    assert w.parse_name("111126_FIRE_U02.mxf")[2] == 1 and keys.media_key("111126_FIRE_V2.mxf") == ("111126_FIRE", 2) and keys.media_key("111126_FIRE_U02.mxf") == ("111126_FIRE_U02", 1)

def test_1050_02_the_first_sighting_of_a_version_file_creates_its_clip_id_under_the_same_story(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = base["name_id"]
    m = seen(s, n.lower() + "_v1"); rows = by_name(s)
    assert set(rows) == {n, n + "_V01"} and rows[n + "_V01"]["blaze_story_id"] == base["blaze_story_id"] and rows[n + "_V01"]["version"] == 2001 and m["display_id"] == base["display_id"] + "_V01"
    seen(s, n + "_V01"); seen(s, n + "_U01"); assert len(clips(s)) == 3, "the same file seen again makes no second clip ID"
    assert s.svc("GET", "/svc/match?name=" + n.replace("FIRE", "FIRX") + "_V01")[0] == 404, "no plain clip, no version"

def test_1050_03_switch_off_nothing_is_created_and_the_version_button_works(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch, on=False)
    assert s.svc("GET", "/svc/match?name=" + base["name_id"] + "_V01")[0] == 404 and len(clips(s)) == 1

def test_1050_04_with_the_switch_on_the_plus_version_button_is_refused_and_the_page_is_told(tmp_path, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("VERSION_SUFFIX", "on")
    from test_server import Srv
    srv = Srv(tmp_path, "placeholder"); assert srv.login()[0] == 200
    c = srv.call("POST", "/api/manual", {"rundown": "R", "story": "Fire"})[1]
    assert srv.call("POST", "/api/clips/%d/version" % c["id"], {})[0] == 409 and srv.call("GET", "/api/config")[1]["version_suffix"] is True

def test_1050_05_a_V_file_is_added_next_to_the_clip_and_nothing_is_removed(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = attached_base(s, f, p, base)["name_id"]
    seen(s, n + "_V01"); f.medias.append(media(1002, n + "_V01.mxf")); p.cycle()
    assert len(posts(f)) == 2 and not dels(f) and sorted(in_story(f)) == sorted([n + ".mxf", n + "_V01.mxf"]) and {r["state"] for r in clips(s)} == {"ATTACHED"}
    p.cycle(); p.cycle(); assert len(posts(f)) == 2
    seen(s, n + "_V02"); f.medias.append(media(1003, n + "_V02.mxf")); p.cycle(); assert len(posts(f)) == 3 and not dels(f) and len(in_story(f)) == 3

def test_1050_06_a_U_file_replaces_the_clip_attach_first_remove_after(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = attached_base(s, f, p, base)["name_id"]
    seen(s, n + "_U01"); f.medias.append(media(1002, n + "_U01.mxf")); p.cycle()
    assert len(posts(f)) == 2 and len(dels(f)) == 1 and in_story(f) == [n + "_U01.mxf"], in_story(f)
    seen(s, n + "_U02"); f.medias.append(media(1003, n + "_U02.mxf")); p.cycle()
    assert len(posts(f)) == 3 and len(dels(f)) == 2 and in_story(f) == [n + "_U02.mxf"], "U02 takes the place of U01"

def test_1050_07_an_update_removes_only_the_main_clip_never_an_added_one(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = attached_base(s, f, p, base)["name_id"]
    seen(s, n + "_V01"); f.medias.append(media(1002, n + "_V01.mxf")); p.cycle()
    seen(s, n + "_U01"); f.medias.append(media(1003, n + "_U01.mxf")); p.cycle()
    assert sorted(in_story(f)) == sorted([n + "_V01.mxf", n + "_U01.mxf"]) and len(dels(f)) == 1, in_story(f)

def test_1050_08_an_update_that_arrives_before_the_plain_clip_was_attached_supersedes_it(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = base["name_id"]
    set_state(s, base["display_id"], "ON_NITRO"); seen(s, n + "_U01"); f.medias = [media(1001, n + ".mxf"), media(1002, n + "_U01.mxf")]; p.cycle()
    assert in_story(f) == [n + "_U01.mxf"] and len(posts(f)) == 1 and not dels(f)
    assert by_name(s)[n]["state"] != "ATTACHED", "the plain clip is superseded, never attached"

def test_1050_09_a_V_file_never_supersedes_the_plain_clip(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch); n = base["name_id"]
    set_state(s, base["display_id"], "ON_NITRO"); seen(s, n + "_V01"); f.medias = [media(1001, n + ".mxf"), media(1002, n + "_V01.mxf")]; p.cycle()
    assert sorted(in_story(f)) == sorted([n + ".mxf", n + "_V01.mxf"]) and len(posts(f)) == 2

def test_1050_10_dry_mode_says_what_it_would_do_and_sends_nothing(tmp_path, monkeypatch):
    s, f, p, base = setup(tmp_path, monkeypatch, BLAZE_ATTACH="dry"); n = base["name_id"]
    set_state(s, base["display_id"], "ATTACHED"); seen(s, n + "_U01"); f.medias = [media(1001, n + ".mxf"), media(1002, n + "_U01.mxf")]; f.story_clips["724921"] = [(1001, n + ".mxf")]
    p.cycle(); assert not posts(f) and not dels(f)

def test_1050_11_the_clip_list_tells_the_page_which_clip_it_is_and_how_many_the_story_has(tmp_path, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("VERSION_SUFFIX", "on")
    from test_server import Srv
    srv = Srv(tmp_path, "placeholder"); assert srv.login()[0] == 200
    c = srv.call("POST", "/api/manual", {"rundown": "R", "story": "Fire"})[1]; n = c["name_id"]
    for x in ("_V01", "_U01", "_U02"): assert srv.svc("GET", "/svc/match?name=" + n + x)[0] == 200
    rows = {x["name_id"]: x for x in srv.call("GET", "/api/clips")[1]["clips"]}
    assert rows[n]["story_clips"] == 0 and rows[n]["vlabel"] is None and rows[n]["story_update"] == "U02" and rows[n + "_U02"]["vlabel"] == "U02" and rows[n + "_V01"]["vlabel"] == "V01"      # v10.7.0: no clip is attached yet, so none is "in the story"
    with srv.app.db.tx() as cur: cur.x("UPDATE clip_ids SET state='ATTACHED'")
    rows = {x["name_id"]: x for x in srv.call("GET", "/api/clips")[1]["clips"]}; assert rows[n]["story_clips"] == 4
    assert srv.svc("POST", "/svc/replaced", {"display_id": rows[n + "_U01"]["display_id"], "replaced": [rows[n]["display_id"]]})[1]["marked"] == 1
    rows = {x["name_id"]: x for x in srv.call("GET", "/api/clips")[1]["clips"]}; assert rows[n]["story_clips"] == 3 and rows[n]["replaced_label"] == "U01" and rows[n + "_V01"]["replaced_label"] is None

def quick_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1"); monkeypatch.setenv("VERSION_SUFFIX", "on")
    s, f, p, e = live_env(tmp_path, BLAZE_ATTACH="dry", BLAZE_LIVE_SHOW_IDS=""); assert s.login()[0] == 200
    f.slugs = [slug(724921, "FIRE", 14, 20)]; p.cycle(); base = clips(s)[0]; n = base["name_id"]
    set_state(s, base["display_id"], "ATTACHED"); f.story_clips["724921"] = [(1001, n + ".mxf")]; return s, f, p, n

def ask(s, did):
    with s.app.db.tx() as cur: i = cur.one("SELECT id FROM clip_ids WHERE display_id=?", (did,))["id"]
    return s.call("POST", "/api/clips/%d/quickattach" % i, {"confirm": True})

def test_1050_12_quick_test_on_a_U_clip_does_the_whole_replace_even_in_dry_mode(tmp_path, monkeypatch):
    s, f, p, n = quick_env(tmp_path, monkeypatch)
    m = seen(s, n + "_U01"); f.medias = [media(1001, n + ".mxf"), media(1002, n + "_U01.mxf")]; p.cycle(); assert not posts(f), "dry: nothing is sent by itself"
    assert any("REPLACES version 1" in x for x in watch_lines(p))
    assert ask(s, m["display_id"])[0] == 200; p.cycle(); p.cycle()
    assert len(posts(f)) == 1 and len(dels(f)) == 1 and in_story(f) == [n + "_U01.mxf"], in_story(f)

def test_1050_13_quick_test_on_a_V_clip_adds_it_and_removes_nothing(tmp_path, monkeypatch):
    s, f, p, n = quick_env(tmp_path, monkeypatch)
    m = seen(s, n + "_V01"); f.medias = [media(1001, n + ".mxf"), media(1002, n + "_V01.mxf")]; p.cycle(); assert not posts(f)
    assert ask(s, m["display_id"])[0] == 200; p.cycle(); p.cycle()
    assert len(posts(f)) == 1 and not dels(f) and sorted(in_story(f)) == sorted([n + ".mxf", n + "_V01.mxf"])

def test_1050_14_removing_a_clip_is_refused_while_dry_unless_a_quick_test_was_confirmed(tmp_path, monkeypatch):
    from autoid_lite.blaze.safety import ForbiddenCall
    s, f, p, n = quick_env(tmp_path, monkeypatch)
    with pytest.raises(ForbiddenCall): p.b.delete_clip("724921", "72492100")
    assert not dels(f)
