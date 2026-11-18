"""Story Media Gallery: a story with more than one clip shows all its clips as one card in the Media & IDs pane (thumbnail tile, label, MOS, item, role, state, Play preview).
The server gives the list (GET /api/clips/<id>/history -> story_clips); the page builds the card. A browser is not available in the tests, so the page checks guard what can break silently."""
import pathlib, pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "autoid_lite" / "web" / "index.html"
SHIM = ROOT / "tools" / "standalone_shim.js"
from test_server import Srv

def text(): return PAGE.read_text(encoding="utf-8")

def story(tmp_path, monkeypatch, suffix=True, title="Fire"):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("VERSION_SUFFIX", "on" if suffix else "off")
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    return s, s.call("POST", "/api/manual", {"rundown": "14:00 Bulletin", "story": title})[1]

def sibling(s, base, ending, version, state="ATTACHED", mos=None, item=None, nitro=None, dur=None):
    """another clip ID under the same story (what the watcher does when it sees a _V01 / _U01 file)"""
    with s.app.db.tx() as cur:
        cur.x("INSERT INTO clip_ids(display_id, day, seq, story_id, version, state, created_at, name_id, media_id, item_id, attach_dur) "
              "SELECT display_id || ?, day, seq, story_id, ?, ?, created_at, COALESCE(name_id, display_id) || ?, ?, ?, 41 FROM clip_ids WHERE id=?", (ending, version, state, ending, mos, item, base["id"]))
        cid = cur.q("SELECT id FROM clip_ids WHERE display_id=(SELECT display_id FROM clip_ids WHERE id=?) || ?", (base["id"], ending))[0]["id"]
        if nitro: cur.x("INSERT INTO files(clip_id, nitro_path, state, duration_s, created_at) VALUES(?,?,?,?,?)", (cid, nitro, "ON_NITRO", dur, "2026-11-17T10:00:00+05:30"))
    return cid

def gallery(s, cid): return s.call("GET", "/api/clips/%d/history" % cid)[1]["story_clips"]

def test_a_story_with_three_clips_lists_all_three_base_first(tmp_path, monkeypatch):
    s, base = story(tmp_path, monkeypatch)
    with s.app.db.tx() as cur: cur.x("UPDATE clip_ids SET media_id='1111821', item_id='943490' WHERE id=?", (base["id"],))
    v = sibling(s, base, "_V01", 2001, mos="1111822", item="943491", nitro="/nitro/FIRE_V01.mxf", dur=41.6)
    u = sibling(s, base, "_U01", 1001, state="ON_NITRO", nitro="C:\\ONAIR\\Nov-26\\FIRE_U01.mxf", dur=12)
    g = gallery(s, base["id"]); n = base["display_id"]
    assert [x["label"] for x in g] == ["BASE", "V01", "U01"] and [x["role"] for x in g] == ["original", "additional", "update"]
    assert [x["id"] for x in g] == [base["id"], v, u]
    assert g[0]["mos_object_id"] == "1111821" and g[0]["item_id"] == "943490" and g[1]["mos_object_id"] == "1111822" and g[1]["item_id"] == "943491"
    assert [x["on_nitro"] for x in g] == [False, True, True] and g[1]["file"] == "FIRE_V01.mxf" and g[2]["file"] == "FIRE_U01.mxf" and g[1]["duration_s"] == 41.6, "the file name is the last part of a Unix or a Windows path"
    assert [x["state"] for x in g] == [base_state(s, base), "ATTACHED", "ON_NITRO"] and g[1]["name_id"].endswith("_V01")

def base_state(s, base):
    with s.app.db.tx() as cur: return cur.q("SELECT state FROM clip_ids WHERE id=?", (base["id"],))[0]["state"]

def test_every_clip_of_the_story_gets_the_same_list_and_other_stories_are_not_in_it(tmp_path, monkeypatch):
    s, base = story(tmp_path, monkeypatch); v = sibling(s, base, "_V01", 2001); u = sibling(s, base, "_U02", 1002)
    other = s.call("POST", "/api/manual", {"rundown": "14:00 Bulletin", "story": "Flood"})[1]
    a, b, c = gallery(s, base["id"]), gallery(s, v), gallery(s, u)
    assert a == b == c and [x["label"] for x in a] == ["BASE", "V01", "U02"] and other["id"] not in [x["id"] for x in a]
    assert [x["label"] for x in gallery(s, other["id"])] == ["BASE"], "a story with one clip: the page shows no gallery"

def test_without_the_switch_an_old_numbered_version_is_a_version(tmp_path, monkeypatch):
    s, base = story(tmp_path, monkeypatch, suffix=False); v2 = sibling(s, base, "_V2", 2)
    g = gallery(s, base["id"]); assert [(x["label"], x["role"]) for x in g] == [("BASE", "original"), ("V2", "version")] and g[1]["id"] == v2

def test_the_list_is_login_protected_like_the_history(tmp_path, monkeypatch):
    s, base = story(tmp_path, monkeypatch); s.cookie = None
    assert s.call("GET", "/api/clips/%d/history" % base["id"])[0] == 401

def test_the_page_shows_the_gallery_only_when_the_story_has_more_than_one_clip():
    s = text(); r = s[s.index("function renderRight("):s.index("var pv=")]
    assert "const multi=(h.story_clips||[]).length>1;if(multi)box.append(gallery(c,h))" in r
    assert "if(!multi)box.append(previewBox(c,h))" in r, "one clip: the old Preview box stays; several clips: every row has its own Play preview"
    assert r.index("gallery(c,h)") < r.index('"Media ID (Clip ID)"'), "the gallery sits above the IDs of the open clip"

def test_the_gallery_card_has_what_the_desk_asked_for():
    s = text(); g = s[s.index("function gallery("):s.index("function startPreview(")]
    for t in ("Story Media Gallery", '" clips"', '"MOS: "', '"Item: "', "▶ Play preview", "startPreview(x,", "openStory(x.id)", '"Original"', '"Additional"', '"Update"', "latest", '"Open"', "x.label", "x.name_id"): assert t in g, t
    assert "textContent" not in g and "innerHTML" not in g, "names come from file names: they are added as text, never as HTML"

def test_a_row_outside_the_current_list_is_not_opened_and_says_why():
    s = text(); g = s[s.index("function gallery("):s.index("function startPreview(")]
    assert "clips.some(y=>y.id===x.id)" in g and "Clear the filter to open it" in g      # showDetail resets a selection that is not in the list, so such a row must not call openStory

def test_there_is_one_player_for_the_whole_pane():
    s = text(); assert s.count('document.createElement("video")') == 1 and "function startPreview(c,f){stopPreview();" in s
    assert s.count("startPreview(") >= 3 and 'v.src="/api/clips/"+c.id+"/preview"' in s
    assert "cache" not in s[s.index("function gallery("):s.index("async function showDetail(")].lower(), "the preview still stores nothing"

def test_the_sample_dashboard_has_a_story_with_three_clips():
    js = SHIM.read_text(encoding="utf-8")
    for t in ("story_clips", "_V01", "_U01", "version_suffix: true", '"original"', '"additional"'): assert t in js, t

import os, shutil
FF = shutil.which("ffmpeg")

@pytest.mark.skipif(not FF, reason="ffmpeg is not installed")
def test_play_preview_on_an_added_clip_streams_that_clips_own_file(tmp_path, monkeypatch):
    """the gallery's Play preview on a _V01 row calls the preview of THAT clip ID: its own Nitro file is converted, not the base clip's"""
    from test_preview import mxf, get
    nitro = tmp_path / "ONAIR" / "Nov-26" / "17-11-2026"; nitro.mkdir(parents=True); f = nitro / "171126_FIRE_V01.mxf"; mxf(f)
    monkeypatch.setenv("NITRO_DIR", str(tmp_path / "ONAIR"))
    s, base = story(tmp_path, monkeypatch); v = sibling(s, base, "_V01", 2001, nitro=str(f), dur=2)
    assert gallery(s, base["id"])[1]["file"] == "171126_FIRE_V01.mxf" and get(s, base["id"])[0] == 404, "the base clip has no file on Nitro, so its own Play says so"
    st, ct, cl, body = get(s, v); assert st == 200 and ct == "video/mp4" and body[4:8] == b"ftyp", (st, ct, body[:60])
