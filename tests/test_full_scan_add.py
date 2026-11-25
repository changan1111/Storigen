"""v11.1.0: Add media > 'Full scan' check box (OFF by default). Off: nothing changes. On: the typed text is searched in ALL of Blaze's media (read only, through the poller) and the editor picks a file.
Quick Support's two source files stay pinned (see test_bot_and_delete_icon.py): the new code lives in api_fullscan.py and blaze/fullscan.py."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_blaze_poll import env, clips, posts, media, slug
from test_quick_test_button import dry, run
from test_support_menu import add, job, jobs, state

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
API = (ROOT / "autoid_lite" / "api_fullscan.py").read_text(encoding="utf-8")
POLL = (ROOT / "autoid_lite" / "blaze" / "fullscan.py").read_text(encoding="utf-8")

def test_checkbox_is_off_by_default_and_the_scan_is_read_only():
    assert 'fs.type="checkbox";fs.id="addfull"' in PAGE and "fs.checked=true" not in PAGE and "fs.defaultChecked" not in PAGE
    assert "/api/support/find" in PAGE and "Full scan" in PAGE
    assert "def a_sup_find" in API and "len(text) < 3" in API and "def sup_list" in POLL and "return super().sup_list(j)" in POLL
    assert ".attach(" not in POLL and "post(" not in API.replace("sup_post", ""), "the scan itself never writes to Blaze"

def _story(tmp_path):
    s, f, p, e = dry(tmp_path); f.slugs = f.slugs + [slug(724921, "AUTO ID 05", 14, 20)]; p.cycle()
    return s, f, p, [x for x in clips(s) if x["blaze_story_id"] == "724921"][0]["display_id"]

def _find(s, p, name):
    st, body = s.call("POST", "/api/support/find", {"rundown": "34427", "story": "724921", "name": name}); assert st == 200, body
    run(p); return job(s, body["id"])

def test_scan_lists_every_file_with_the_name_then_the_pick_is_attached_once(env, tmp_path):
    s, f, p, did = _story(tmp_path); base = did[:14]
    f.medias.append(media(1103586, base + "_SVO.mxf")); f.medias.append(media(1103587, base + "_SVO_V01.mxf")); f.medias.append(media(1103588, "OTHER_THING.mxf"))
    j = _find(s, p, base); assert j["state"] == "DONE" and not posts(f), "a scan sends nothing"
    names = sorted(x["name"] for x in j["result"]["media"]); assert len(names) == 2 and all(base in n for n in names)
    pick = [x for x in j["result"]["media"] if not x["name"].replace(".mxf", "").endswith("_V01")][0]
    assert all(x["kind"] != "LIST" for x in jobs(s)), "scan requests are not shown in the queue"
    st, body = add(s, media_id=pick["media_id"], full_scan=True, media_title=pick["name"]); assert st == 200
    run(p); assert [x["mosObjectId"] for x in posts(f)] == [pick["media_id"]] and job(s, body["id"])["state"] == "DONE" and state(s, did) == "ATTACHED"
    run(p); assert len(posts(f)) == 1

def test_scan_edge_cases_and_the_old_requests_still_work(env, tmp_path):
    s, f, p, did = _story(tmp_path)
    assert s.call("POST", "/api/support/find", {"rundown": "34427", "story": "724921", "name": "ab"})[0] == 422
    assert s.call("POST", "/api/support/find", {"rundown": "34427", "story": "nope", "name": "abcd"})[0] in (400, 404)
    assert add(s, media_id="12", full_scan=True, media_title="221126_X")[1] is not None and add(s, media_id="12", full_scan=True)[0] == 400, "a scan pick needs its title"
    assert s.call("POST", "/api/support/add", {"rundown": "34427", "story": "724921", "media_id": "1103586", "media_title": "A_B", "full_scan": True})[0] == 400, "never without the Yes"
    assert add(s, media_id="x1", full_scan=True, media_title="221126_X")[0] == 400, "the id must be a number"
    assert add(s, media_id="999999")[0] == 404, "without full_scan the old rule is unchanged"
    j = _find(s, p, "NO_SUCH_FILE"); assert j["state"] == "DONE" and j["result"]["media"] == []

def test_a_clip_on_nitro_skips_the_settle_wait_but_a_converting_file_still_waits(env, tmp_path):
    """v11.1: ON_NITRO = final file. A file Blaze changed 5 s ago is attached at once for an ON_NITRO clip; BLAZE_SETTLE_ON_NITRO=0 brings the wait back."""
    from autoid_lite.blaze.poller import Poller
    class C: settle = 60; settle_on_nitro_skip = True
    p = Poller.__new__(Poller); p.c = C()
    assert p.settle_for({"state": "ON_NITRO"}) == 0 and p.settle_for({"state": "WAITING"}) == 60
    C.settle_on_nitro_skip = False; assert p.settle_for({"state": "ON_NITRO"}) == 60
    from autoid_lite.blaze.keys import judge
    m = {"id": 1, "title": "X", "duration": 5000, "status": "UPDATED", "modifiedDate": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    assert judge([m], 0)[0] == "found" and judge([m], 60)[0] == "settling"
    assert judge([dict(m, status="NEW", duration=0)], 0)[0] == "converting", "Blaze must still have converted it"
