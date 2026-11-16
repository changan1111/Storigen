"""BLAZE_SHOW_IDS=auto: the poller asks Blaze for the broadcast day's shows (the call captured from the rundown panel), follows all of them (hot shows every pass, cold ones rarely),
allows live by time slot (masterId), and keeps the story's script duration in step after a live attach."""
import os as _os; _os.environ.setdefault("ID_FORMAT", "legacy")      # these tests pin the legacy YYYYMMDD_NNNNC_ ID; test_clip_names_and_versions.py covers DDMMYY_STORY_NAME
import datetime as dt, pathlib, re, sys, urllib.parse as up
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "tools")); sys.path.insert(0, str(root))
from test_server import Srv
from test_blaze_poll import env, Fake, bp, slug, media, clips, set_state, live_env, ready_clip, posts, watch_lines     # noqa: F401

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

def show(sid, title, start_in_min, slugs, master):
    t = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=start_in_min)).astimezone(IST).isoformat(timespec="seconds")
    return {"id": sid, "title": title, "startTime": t, "slugCount": slugs, "masterId": master, "duration": 1800, "templateId": 1, "status": {"id": 1}}

def auto_env(tmp_path, **extra):
    s = Srv(tmp_path, "story_id"); f = Fake()
    cfg = bp.Cfg({"BLAZE_URL": "http://127.0.0.1:%d" % f.port, "BLAZE_SESSION_ID": "SID", "BLAZE_USERNAME": "u", "BLAZE_SHOW_IDS": "auto", "WEB_PORT": str(s.port), "SERVICE_API_KEY": "k" * 20,
                  "BLAZE_LEDGER": str(tmp_path / "ledger.db"), "BLAZE_REPORT_DIR": str(tmp_path / "reports"), "BLAZE_IGNORE_TITLES": "BREAK", "BLAZE_MEDIA_RETRY_SECS": "0", "BLAZE_INFO_SECS": "0", **extra})
    return s, f, bp.Poller(cfg)

def reads(f, sid): return len([x for x in f.log if x[1].startswith("/DataService/shows/%s/slugs" % sid)])

def test_auto_mode_follows_every_show_of_the_day_and_skips_ignored_titles(tmp_path):
    s, f, p = auto_env(tmp_path, BLAZE_IGNORE_SHOW_TITLES="TEST SHOW")
    f.show_list = [show(100, "07_11_14:00 PM Bulletin", 30, 11, 12), show(101, "07_11_23:00 PM Bulletin", 600, 11, 13), show(102, "07_11_test show 7", 30, 3, 99)]
    f.slugs_by_show = {"100": [slug(1, "A", 1)], "101": [slug(2, "B", 1)]}; p.cycle()
    assert p.c.shows == ["100", "101"]
    q = [up.unquote(x[1]) for x in f.log if x[1].startswith("/DataService/shows?")]
    assert q and re.search(r'"fromDate":"\d\d/\d\d/\d\d","toDate":"\d\d/\d\d/\d\d"', q[0]) and "channelId=1" in q[0]            # DD/MM/YY, as the page sends it
    assert {r["blaze_rundown_id"] for r in clips(s)} == {"100", "101"} and p.names["100"][0] == "07_11_14:00 PM Bulletin"
    assert len([x for x in watch_lines(p) if "NEW SHOW " in x]) == 2

def test_many_new_shows_are_one_summary_line_not_thirty_six(tmp_path):
    s, f, p = auto_env(tmp_path); f.show_list = [show(200 + i, "09_11_%02d:00 AM Bulletin" % i, 30 + 30 * i, 11, 12 + i) for i in range(8)]; f.slugs = []; p.cycle()
    L = [x for x in watch_lines(p) if "NEW SHOW" in x]; assert len(L) == 1 and "NEW SHOWS" in L[0] and "8 shows" in L[0] and "ids 200 to 207" in L[0]
    p.list_at = 0; p.cycle(); assert len([x for x in watch_lines(p) if "NEW SHOW" in x]) == 1, "not repeated"

def test_an_empty_or_odd_list_never_drops_the_shows_being_followed(tmp_path):
    s, f, p = auto_env(tmp_path); f.show_list = [show(100, "x", 30, 1, 12)]; f.slugs = [slug(1, "A", 1)]; p.cycle(); assert p.c.shows == ["100"]
    f.show_list = []; p.list_at = 0; p.cycle(); assert p.c.shows == ["100"]
    f.show_list = [show(105, "next", 30, 1, 12)]; p.list_at = 0; p.cycle(); assert p.c.shows == ["105"] and "100" not in p.fails

def test_auto_mode_live_is_allowed_by_time_slot_only(tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_SHOW_IDS="auto", BLAZE_LIVE_SHOW_IDS="", BLAZE_LIVE_MASTER_IDS="13")
    f.show_list = [show(34427, "05_11_14:30 PM Bulletin", 30, 1, 13)]; ready_clip(s, f, p); p.cycle(); assert len(posts(f)) == 1
    s2, f2, p2, e2 = live_env(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, BLAZE_SHOW_IDS="auto", BLAZE_LIVE_SHOW_IDS="", BLAZE_LIVE_MASTER_IDS="14")
    f2.show_list = [show(34427, "05_11_14:30 PM Bulletin", 30, 1, 13)]; ready_clip(s2, f2, p2); p2.cycle(); assert not posts(f2) and any("not allowed for live" in x for x in watch_lines(p2))

def test_auto_mode_live_needs_a_slot_or_ids(tmp_path):
    base = {"BLAZE_SHOW_IDS": "auto", "BLAZE_ATTACH": "live", "BLAZE_LIVE_CONFIRM": "YES_ATTACH_FOR_REAL"}
    assert bp.Cfg(base).attach == "live"      # v9.7.5: live alone = every show; the slot / ids only narrow it
    assert bp.Cfg({**base, "BLAZE_LIVE_MASTER_IDS": "13"}).live_masters == {"13"}
    c = bp.Cfg({"BLAZE_SHOW_IDS": "auto"}); assert c.auto and c.shows == [] and c.heartbeat == "page" and c.verified == {"20", "21"}

def test_script_duration_is_set_after_a_live_attach_like_the_page_does(tmp_path):
    s, f, p, e = live_env(tmp_path); ready_clip(s, f, p); p.cycle()
    assert f.puts == [("724921", "1", {"scriptDur": "50", "wpm": "100"})] and any("DURATION SET" in x and "50 s" in x for x in watch_lines(p))

def test_script_duration_is_left_alone_for_stories_with_script_time_or_when_switched_off(tmp_path):
    s, f, p, e = live_env(tmp_path); f.script_dur["724921"] = 30; ready_clip(s, f, p); p.cycle()
    assert len(posts(f)) == 1 and not f.puts and any("DURATION NOT SET" in x and "already has 30 s" in x for x in watch_lines(p))
    d = tmp_path / "off"; d.mkdir(); s2, f2, p2, e2 = live_env(d, BLAZE_LIVE_SCRIPTDUR="0"); ready_clip(s2, f2, p2); p2.cycle(); assert len(posts(f2)) == 1 and not f2.puts

def test_undo_puts_the_duration_back_in_step(tmp_path):
    s, f, p, e = live_env(tmp_path); did = ready_clip(s, f, p); p.cycle(); assert f.puts[-1][2]["scriptDur"] == "50"
    out = p.led and bp.undo(p.c, p.b, [did]); assert "removed Blaze clip" in out and "script duration was set to 0 s" in out and f.puts[-1] == ("724921", "1", {"scriptDur": "0", "wpm": "100"})

def test_the_duration_update_is_the_only_new_write_and_only_while_live(env):
    s, f, p = env; assert p.c.attach == "dry"
    with pytest.raises(bp.ForbiddenCall): p.b.set_script_dur("5", "1", 50, 100)
    for m, path in (("PUT", "/DataService/stories/5/versions/1/lock"), ("PUT", "/DataService/stories/5/versions/x"), ("POST", "/DataService/stories/5/versions/1"), ("DELETE", "/DataService/stories/5/versions/1")):
        with pytest.raises(bp.ForbiddenCall): p.b.call(m, path)
    assert f.log == [], "nothing reached Blaze"
