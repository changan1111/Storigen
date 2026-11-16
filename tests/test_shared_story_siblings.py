"""v9.11: a story that sits in several bulletins has one clip ID per bulletin (same clip NAME). When the file is in that story, ALL its clip IDs are attached,
not only the first one (field test: 13 of 28 clips stayed OVERDUE although the poller logged 'already in story: nothing to do')."""
import sys, pathlib
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_server import Srv
from test_blaze_poll import Fake, slug, media, clips, posts, bp, LIVE

def mk(tmp_path, monkeypatch, **extra):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1")
    s = Srv(tmp_path, "story_id"); f = Fake()
    e = {"BLAZE_URL": "http://127.0.0.1:%d" % f.port, "BLAZE_SESSION_ID": "SID", "BLAZE_USERNAME": "u", "BLAZE_SHOW_IDS": "34427,34428", "WEB_PORT": str(s.port), "SERVICE_API_KEY": "k" * 20,
         "BLAZE_MEDIA_SETTLE_SECS": "60", "BLAZE_MEDIA_RETRY_SECS": "0", "BLAZE_INFO_SECS": "0", "BLAZE_LEDGER": str(tmp_path / "ledger.db"), "BLAZE_REPORT_DIR": str(tmp_path / "reports"), **extra}
    return s, f, bp.Poller(bp.Cfg(e))

def shared_story(s, f, p, n=2):
    a = slug(731375, "HL ONLY SLM - SCHOOL ISSUE 1 PM", 49, 25)
    f.slugs_by_show = {"34427": [a], "34428": [dict(a, id=a["id"] + 500)]}; p.cycle()
    rows = clips(s); assert len(rows) == 2 and len({r["name_id"] for r in rows}) == 1 and rows[0]["blaze_rundown_id"] != rows[1]["blaze_rundown_id"]
    return rows, rows[0]["name_id"].replace("_", " ") + ".mxf"

def test_911_01_desk_attach_marks_every_clip_id_of_the_shared_story(tmp_path, monkeypatch):
    s, f, p = mk(tmp_path, monkeypatch); rows, fname = shared_story(s, f, p)          # NAS never mounted: the state is still WAITING_FOR_CLIP
    f.medias = [media(1113224, fname)]; p.cycle()
    f.story_clips = {"731375": [(1113224, fname)]}; p.last_rec = 0; p.cycle()           # the desk attaches once, in the story both bulletins share
    assert sorted(r["state"] for r in clips(s)) == ["ATTACHED", "ATTACHED"]
    txt = p.report(write=False); assert "AGREE 2" in txt and "OVERDUE" not in txt
    assert not [x for x in f.log if x[0] == "POST"]

def test_911_02_watcher_mode_still_needs_the_watcher_for_the_read_back(tmp_path, monkeypatch):
    s, f, p = mk(tmp_path, monkeypatch, BLAZE_ATTACH_WHEN="watcher"); rows, fname = shared_story(s, f, p)
    f.medias = [media(1113224, fname)]; p.cycle(); f.story_clips = {"731375": [(1113224, fname)]}; p.last_rec = 0; p.cycle()
    assert sorted(r["state"] for r in clips(s)) == ["WAITING_FOR_CLIP", "WAITING_FOR_CLIP"]      # unchanged strict behaviour when the NAS watcher is the rule

def test_911_03_file_attached_twice_in_the_story_is_still_a_duplicate(tmp_path, monkeypatch):
    s, f, p = mk(tmp_path, monkeypatch); rows, fname = shared_story(s, f, p)
    f.medias = [media(1113224, fname)]; p.cycle(); f.story_clips = {"731375": [(1113224, fname), (1113224, fname)]}; p.last_rec = 0; p.cycle()
    assert "DUPLICATE" in p.report(write=False) and all(r["state"] != "ATTACHED" for r in clips(s))

def test_911_04_a_wrong_media_flag_cannot_bypass_the_state_check(tmp_path, monkeypatch):
    """The server accepts the media_mode shortcut only from the Blaze read-back, and only as the JSON true."""
    s, f, p = mk(tmp_path, monkeypatch); rows, fname = shared_story(s, f, p); r0 = rows[0]
    body = {"display_id": r0["display_id"], "blaze_rundown_id": r0["blaze_rundown_id"], "blaze_story_id": r0["blaze_story_id"]}
    assert s.svc("POST", "/svc/attach/confirm", dict(body, source="blaze_readback", media_mode="yes"))[1]["ok"] is False
    assert s.svc("POST", "/svc/attach/confirm", dict(body, source="mos_item", media_mode=True))[1]["ok"] is False
    assert s.svc("POST", "/svc/attach/confirm", dict(body, source="blaze_readback", media_mode=True))[1]["ok"] is True
