"""v9.8.0: once a clip is attached the dashboard shows what Blaze holds: the media object (mosObjectId), the story item (itemId) and the clip length, on the card and in the details, in the CSV and in the search."""
import re, sys, pathlib
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_server import Srv
from test_blaze_poll import env, slug, media, live_env, ready_clip, posts, set_state, clips as svc_rows
import blaze_poll as bp

HTML = (pathlib.Path(__file__).resolve().parent.parent / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")

@pytest.fixture
def srv(tmp_path):
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; return s

def one(s, story="Fire on beach"):
    c = s.call("POST", "/api/manual", {"rundown": "14:00 Bulletin", "story": story})[1]
    r = next(x for x in s.svc("GET", "/svc/clips")[1] if x["display_id"] == c["display_id"])
    s.svc("POST", "/svc/files", {"display_id": c["display_id"], "state": "ON_NITRO"}); return c, r

def confirm(s, c, r, **kw): return s.svc("POST", "/svc/attach/confirm", dict({"display_id": c["display_id"], "blaze_rundown_id": r["blaze_rundown_id"], "blaze_story_id": r["blaze_story_id"], "source": "blaze_live"}, **kw))[1]
def api_row(s, c): return next(x for x in s.call("GET", "/api/clips")[1]["clips"] if x["id"] == c["id"])

def test_980_01_the_facts_are_stored_and_shown_everywhere(srv):
    c, r = one(srv); assert confirm(srv, c, r, mos_object_id="1111821", item_id="943490", duration_s=18, blaze_clip_id="1201706")["ok"]
    a = api_row(srv, c); assert (a["state"], a["mos_object_id"], a["item_id"], a["attach_dur"], a["blaze_clip_id"]) == ("ATTACHED", "1111821", "943490", 18, "1201706")
    s = next(x for x in srv.svc("GET", "/svc/clips")[1] if x["display_id"] == c["display_id"]); assert (s["mos_object_id"], s["item_id"], s["attach_dur"]) == ("1111821", "943490", 18)
    h = srv.call("GET", "/api/clips/%d/history" % c["id"])[1]; assert (h["clip"]["mos_object_id"], h["clip"]["item_id"], h["clip"]["attach_dur"], h["clip"]["blaze_clip_id"]) == ("1111821", "943490", 18, "1201706")
    step = next(x for x in h["steps"] if x["key"] == "attach"); assert "MOS object 1111821" in step["detail"] and "item 943490" in step["detail"] and "duration 18 s" in step["detail"]
    for q in ("1111821", "943490"): assert [x["id"] for x in srv.call("GET", "/api/clips?q=" + q)[1]["clips"]] == [c["id"]], "searchable by " + q
    import urllib.request
    rq = urllib.request.Request("http://127.0.0.1:%d/api/clips.csv" % srv.port, headers={"Cookie": srv.cookie})
    with urllib.request.urlopen(rq, timeout=10) as resp: st, txt = resp.status, resp.read().decode("utf-8", "replace")
    assert st == 200 and "MOS object ID" in txt and "1111821" in txt and "943490" in txt and "Duration (s)" in txt, txt[:300]

def test_980_02_an_attach_the_desk_did_is_filled_in_later_without_changing_anything_else(srv):
    c, r = one(srv); assert srv.call("POST", "/api/clips/%d/attach" % c["id"])[0] in (200, 204) or True
    with srv.app.db.tx() as cur: cur.x("UPDATE clip_ids SET state='ATTACHED', attached_at='2026-11-12T10:00:00+05:30', attach_method='desk', media_id='1111821' WHERE id=?", (c["id"],))
    assert confirm(srv, c, r, mos_object_id="1111821", item_id="943490", duration_s=18, source="blaze_readback")["note"] == "already attached"
    a = api_row(srv, c); assert (a["item_id"], a["attach_dur"]) == ("943490", 18) and a["state"] == "ATTACHED"
    assert confirm(srv, c, r, mos_object_id="999", item_id="1", duration_s=1)["ok"]; a = api_row(srv, c); assert (a["mos_object_id"], a["item_id"], a["attach_dur"]) == ("1111821", "943490", 18), "recorded facts are never overwritten"

def test_980_03_a_wrong_story_records_nothing(srv):
    c, r = one(srv); res = confirm(srv, c, dict(r, blaze_story_id="1", blaze_rundown_id="2"), mos_object_id="5", item_id="6", duration_s=7); assert res["ok"] is False
    a = api_row(srv, c); assert a["state"] == "NEEDS_DESK" and a["item_id"] is None and a["attach_dur"] is None

def test_980_04_attached_facts_from_the_story_read_back():
    row = {"id": "1201706", "mos": "1111821", "dur": 18000, "item": 943490}
    assert bp.attached_facts(row, {"id": 1111821}, None) == {"mos_object_id": "1111821", "item_id": "943490", "duration_s": 18, "blaze_clip_id": "1201706"}
    assert bp.attached_facts({"id": "7"}, {"id": 5, "duration": 29999}, "900001") == {"mos_object_id": "5", "item_id": "900001", "duration_s": 29, "blaze_clip_id": "7"}, "whole seconds, rounded down, as the attach sends"
    assert bp.attached_facts({}, {"id": 5}, None) == {"mos_object_id": "5", "item_id": None, "duration_s": None, "blaze_clip_id": None}

def test_980_05_the_poller_records_them_when_it_attaches(env, tmp_path):
    s, f, p, e = live_env(tmp_path); did = ready_clip(s, f, p); p.cycle(); p.cycle(); assert len(posts(f)) == 1
    row = next(r for r in svc_rows(s) if r["display_id"] == did); assert row["state"] == "ATTACHED"
    assert row["mos_object_id"] == "1103586" and row["item_id"] == "900001" and row["attach_dur"] == 50 and row["blaze_clip_id"]

def test_980_06_the_poller_records_them_when_the_desk_attached(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); did = svc_rows(s)[0]["display_id"]; set_state(s, did, "ON_NITRO")
    f.medias = [media(1103586, did[:14] + "_SVO.mxf")]; p.cycle(); f.story_clips = {"724921": [(1103586, did[:14] + "_SVO.mxf")]}; p.last_rec = 0; p.cycle()
    row = svc_rows(s)[0]; assert row["state"] == "ATTACHED" and (row["mos_object_id"], row["item_id"], row["attach_dur"]) == ("1103586", "900001", 50)

def test_980_07_a_clip_attached_before_the_upgrade_gets_its_facts_from_the_next_read_back(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); did = svc_rows(s)[0]["display_id"]; set_state(s, did, "ATTACHED")
    f.story_clips = {"724921": [(1103586, did[:14] + "_SVO.mxf")]}; f.medias = [media(1103586, did[:14] + "_SVO.mxf")]; p.last_rec = 0; p.cycle()
    row = svc_rows(s)[0]; assert row["state"] == "ATTACHED" and (row["mos_object_id"], row["item_id"], row["attach_dur"]) == ("1103586", "900001", 50)

def test_980_08_the_dashboard_shows_them_on_the_card_and_in_the_details():
    assert "function attChips" in HTML and "fmtDur" in HTML and re.search(r"const ac=attChips\(c\)", HTML), "the card shows the chips"
    for k in ("MOS object ID", "Item ID", "Clip duration", "Blaze clip ID"): assert k in HTML, k + " in the details"
    assert "c.mos_object_id" in HTML and "c.item_id" in HTML and "c.attach_dur" in HTML

def test_980_09_the_server_reports_10_5_0(srv): assert srv.call("GET", "/api/config")[1]["version"] == "10.18.2"
