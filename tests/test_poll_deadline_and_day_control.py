"""v9.5.0: what the merge added on top of the venkat engine: deadline-bounded reads, quick retry, close-day / open-day, the story name and bulletin time reaching the dashboard,
the extra filters and the multi-word search, the bulletin list, and the /svc/clips limit check."""
import os as _os; _os.environ.setdefault("ID_FORMAT", "legacy")      # these tests pin the legacy YYYYMMDD_NNNNC_ ID; test_clip_names_and_versions.py covers DDMMYY_STORY_NAME
import pathlib, sys, threading, time
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "tools")); sys.path.insert(0, str(root))
import blaze_snapshot as snap
from test_server import Srv
from test_blaze_poll import Fake, clips, bp                                                      # noqa: F401
from test_autoshows import show, auto_env                                                        # noqa: F401
from test_polling_engine import world, kinds, day
from test_dashboard import web, make                                                             # noqa: F401

# ---------------------------------------------------------------- Fan: bounded reads with a deadline
def test_fan_a_slow_read_is_never_started_twice_and_its_answer_is_used_later():
    fan = snap.Fan(4); calls = []; gate = threading.Event()
    def slow(): calls.append(1); gate.wait(5); return "late answer"
    res, harv, late, busy = fan.run({"a": slow, "b": lambda: "fast"}, time.monotonic() + 0.3)
    assert res["b"].value == "fast" and "a" in late and not harv
    res2, harv2, late2, busy2 = fan.run({"a": slow}, time.monotonic() + 0.1)
    assert "a" in busy2 and len(calls) == 1, "the read still running is not requested again"
    gate.set(); time.sleep(0.3); res3, harv3, _, _ = fan.run({}, time.monotonic() + 0.1)
    assert harv3["a"].value == "late answer" and len(calls) == 1
    fan.close()

def test_fan_one_failure_does_not_touch_the_others():
    fan = snap.Fan(4)
    def boom(): raise RuntimeError("x")
    res, _, late, _ = fan.run({"a": boom, "b": lambda: 2}, time.monotonic() + 2)
    assert not res["a"].ok and isinstance(res["a"].exc, RuntimeError) and res["b"].ok and not late
    fan.close()

def test_the_poller_round_ends_at_its_deadline_when_blaze_is_slow_and_uses_the_late_answers_next_round(tmp_path):
    s, f, p = auto_env(tmp_path, BLAZE_CYCLE_DEADLINE_SECS="1", BLAZE_POLL_SECS="5"); world(f, shows=4, per=3); p.cycle()
    assert set(p.snapv) == {"1000", "1001", "1002", "1003"}
    f.delay = 4.0; t = time.monotonic(); p.cycle(); took = time.monotonic() - t
    assert took < 3.2, "each phase gave up at the 1 s deadline (round %.1f s); waiting for the 4 s answers would take 4 s for the slug lists alone" % took
    assert p.stats.late >= 1 and not p.fails.get("1000"), "late is not a failure"
    f.delay = 0; time.sleep(4.5); p.cycle(); assert p.stats.ok >= 1

# ---------------------------------------------------------------- retry of a transient failure
def test_a_transient_blaze_error_is_retried_once_inside_the_round(tmp_path):
    s, f, p = auto_env(tmp_path); world(f, shows=2, per=2); p.cycle()
    calls = {"n": 0}; real = p.b.slugs
    def flaky(show):
        calls["n"] += 1
        if calls["n"] == 1: raise bp.BlazeError(503, "busy")
        return real(show)
    p.b.slugs = flaky; p.cycle()
    assert calls["n"] >= 3 and not p.fails.get("1000") and not p.fails.get("1001"), "one 503 was retried and nothing was marked failed"

def test_an_expired_session_is_not_retried(tmp_path):
    s, f, p = auto_env(tmp_path); world(f, shows=1, per=2); p.cycle(); n = {"n": 0}
    def dead(show): n["n"] += 1; raise bp.SessionExpired("x")
    p.b.slugs = dead
    with pytest.raises(bp.SessionExpired): p.cycle()
    assert n["n"] == 1

# ---------------------------------------------------------------- close-day / open-day
def test_a_closed_day_is_not_read_and_is_not_reported_as_stale_and_open_day_resumes(tmp_path):
    s, f, p = auto_env(tmp_path); world(f, shows=3, per=2); p.cycle(); ok0 = p.stats.req_ok_total
    p.led.put(p.day_key(), "closed"); n_before = len(f.log); p.cycle()
    assert p.closed and not [x for x in f.log[n_before:] if "/slugs" in x[1]], "no slug list is read on a closed day"
    p.last_ok = {k: time.time() - 9999 for k in p.last_ok}; assert p.problem(p.ages()) is None, "paused on purpose: not a stale-shows alarm"
    p.led.delete(p.day_key()); p.cycle(); assert not p.closed and p.stats.req_ok_total > ok0

# ---------------------------------------------------------------- the registry gets the story name and the bulletin time
def test_story_name_and_bulletin_time_reach_the_registry_and_are_searchable(web):
    web.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "1500", "rundown_name": "News at Nine", "rundown_start": "2026-11-10T09:00:00+00:00",
                                           "stories": [{"blaze_story_id": "5001", "slug": "FLOOD", "slug_id": "9001", "position": 1, "story_title": "River bursts its banks"},
                                                       {"blaze_story_id": "5002", "slug": "BUDGET", "slug_id": "9002", "position": 2}]})
    d = web.call("GET", "/api/clips?per_page=50")[1]; r = {c["blaze_story_id"]: c for c in d["clips"]}
    assert r["5001"]["story_title"] == "River bursts its banks" and r["5002"]["story_title"] is None and r["5001"]["show_start"] == "2026-11-10T09:00:00+00:00"
    f = lambda q: sorted(c["blaze_story_id"] for c in web.call("GET", "/api/clips?per_page=50&q=" + q)[1]["clips"])
    assert f("river") == ["5001"], "story name"
    assert f("9002") == ["5002"] and f("5001") == ["5001"] and f("1500") == ["5001", "5002"], "slug id, story id, show id"
    assert f("news%20ten") == [] and f("news%20nine") == ["5001", "5002"], "bulletin name, every word must match"
    assert f("flood%20river") == ["5001"], "words may sit in different fields"
    b = web.call("GET", "/api/clips?per_page=50")[1]["bulletins"]; assert [x["id"] for x in b] == ["1500"] and b[0]["m"] == 2 and b[0]["wait"] == 2 and b[0]["nitro"] == 0 and b[0]["start"].startswith("2026-11-10T09")
    h = web.call("GET", "/api/clips/%d/history" % r["5001"]["id"])[1]["clip"]; assert h["story_title"] == "River bursts its banks" and h["show_start"].startswith("2026-11-10")

def test_the_bulletin_time_is_searchable_in_the_servers_local_time(web):
    import datetime as dt
    start = "2026-11-10T09:00:00+00:00"
    web.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "1600", "rundown_name": "Bulletin", "rundown_start": start, "stories": [{"blaze_story_id": "6001", "slug": "X", "slug_id": "1", "position": 1}]})
    loc = dt.datetime.fromisoformat(start).astimezone().strftime("%H:%M")
    assert web.call("GET", "/api/clips?per_page=50&q=" + loc.replace(":", "%3A"))[1]["total"] == 1 and web.call("GET", "/api/clips?per_page=50&q=" + loc.replace(":", ""))[1]["total"] == 1
    other = (dt.datetime.fromisoformat(start).astimezone() + dt.timedelta(hours=3)).strftime("%H:%M")
    assert web.call("GET", "/api/clips?per_page=50&q=" + other.replace(":", "%3A"))[1]["total"] == 0

def test_ready_and_attention_filters_and_a_bad_filter(web):
    for i in range(3): web.svc("POST", "/svc/stories", {"blaze_rundown_id": "1", "blaze_story_id": str(100 + i), "slug": "S%d" % i, "rundown_name": "A"})
    ids = [c["display_id"] for c in web.call("GET", "/api/clips?per_page=50")[1]["clips"]]
    web.svc("POST", "/svc/files", {"display_id": ids[0], "state": "ON_NITRO", "nitro_path": "/n/a.mxf"}); web.svc("POST", "/svc/files", {"display_id": ids[1], "state": "NEEDS_DESK", "error": "x"})
    g = lambda f: web.call("GET", "/api/clips?per_page=50&filter=" + f)[1]
    assert g("nitro")["total"] == 1 and g("attention")["total"] == 1 and g("action")["total"] == 2 and g("waiting")["total"] == 1
    assert web.call("GET", "/api/clips?filter=bogus")[0] == 400

def test_svc_clips_limit_is_checked_and_a_full_day_is_not_cut_at_500(web):
    for i in range(0, 600, 100):
        web.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": str(2000 + i), "rundown_name": "R%d" % i, "stories": [{"blaze_story_id": str(i * 10 + k), "slug": "S", "slug_id": str(i * 10 + k), "position": k} for k in range(1, 101)]})
    assert len(web.svc("GET", "/svc/clips")[1]) == 600, "default is no longer 500"
    assert len(web.svc("GET", "/svc/clips?limit=10")[1]) == 10 and web.svc("GET", "/svc/clips?limit=abc")[0] == 422

def test_the_ledger_can_forget_a_key(tmp_path):
    import blaze_ledger as bl
    led = bl.Ledger(str(tmp_path / "l.db")); led.put("k", "1"); assert led.get("k") == "1"; led.delete("k"); assert led.get("k") is None
def test_day_counts_ignore_the_show_filter_and_search(web):
    web.svc('POST','/svc/rundowns/sync',{'blaze_rundown_id':'1','rundown_name':'A','stories':[{'blaze_story_id':'1','slug':'ONE','slug_id':'1','position':1}]})
    web.svc('POST','/svc/rundowns/sync',{'blaze_rundown_id':'2','rundown_name':'B','stories':[{'blaze_story_id':'2','slug':'TWO','slug_id':'2','position':1}]})
    d = web.call('GET','/api/clips?per_page=50&show=1&q=one')[1]
    assert d['counts']['all'] == 1 and d['day_counts']['all'] == 2 and d['day_counts']['waiting'] == 2

# ---------------------------------------------------------------- v9.5.1: shows just after midnight are followed from the evening on
import datetime as dt

def _la_env(tmp_path, ends_in_h=2.0, **extra):
    """A poller whose Blaze lists shows by calendar date (stubbed) and whose broadcast day ends `ends_in_h` hours from now."""
    s, f, p = auto_env(tmp_path, **extra); now = dt.datetime.now(dt.timezone.utc); day = p.server_day()
    real = p.a.call
    p.a.call = lambda path, *a, **k: dict(real(path, *a, **k), day_ends=(now + dt.timedelta(hours=ends_in_h)).isoformat(timespec="seconds")) if path == "/svc/status" else real(path, *a, **k)
    def at(h, sid, title): return {"id": str(sid), "title": title, "start": (now + dt.timedelta(hours=h)).isoformat(timespec="seconds"), "slugs": 3, "master": None}
    f.slugs = []; return s, f, p, day, at

def test_lookahead_follows_a_show_after_midnight_but_not_one_that_belongs_to_the_next_broadcast_day(tmp_path):
    s, f, p, day, at = _la_env(tmp_path)
    tonight, midnight, night, morning = at(-1, 100, "evening bulletin"), None, at(1.0, 200, "00:00 bulletin"), at(3.0, 300, "05:30 bulletin")        # the day ends in 2 h: 'morning' starts after it
    p.b.day_shows = lambda d1, d2=None: [tonight] if d1 == day else [night, morning] if d1 == day + dt.timedelta(days=1) else []
    p.cycle(); assert set(p.c.shows) == {"100", "200"}, "the 00:00 show is followed; the 05:30 show waits for the day to roll over"

def test_lookahead_window_is_hours_from_now(tmp_path):
    s, f, p, day, at = _la_env(tmp_path, ends_in_h=8, BLAZE_SHOW_LOOKAHEAD_HOURS="2")
    near, far = at(1.0, 200, "near"), at(5.0, 300, "far")
    p.b.day_shows = lambda d1, d2=None: [] if d1 == day else [near, far]
    p.cycle(); assert p.c.shows == ["200"], "in 2 h yes, in 5 h not yet (even though the day does not end for 8 h)"

def test_lookahead_can_be_switched_off_and_a_failure_does_not_break_the_normal_list(tmp_path):
    s, f, p, day, at = _la_env(tmp_path, BLAZE_SHOW_LOOKAHEAD_HOURS="0")
    p.b.day_shows = lambda d1, d2=None: [at(-1, 100, "evening")] if d1 == day else [at(1, 200, "night")]; p.cycle(); assert p.c.shows == ["100"]
    (tmp_path / "b").mkdir(); s, f, p, day, at = _la_env(tmp_path / "b")
    def lst(d1, d2=None):
        if d1 == day: return [at(-1, 100, "evening")]
        raise OSError("Blaze hiccup")
    p.b.day_shows = lst; p.cycle(); assert p.c.shows == ["100"], "the look-ahead is a bonus: a failure there never empties or breaks the list"

def test_the_show_followed_early_stays_followed_when_the_day_rolls_over(tmp_path):
    s, f, p, day, at = _la_env(tmp_path)
    night = at(1.0, 200, "00:00 bulletin"); nxt = day + dt.timedelta(days=1)
    p.b.day_shows = lambda d1, d2=None: [] if d1 == day else [night]
    p.cycle(); assert p.c.shows == ["200"] and p.show_day["200"] == day.isoformat()
    real_status = p.a.call; p.a.call = lambda path, *a, **k: dict(real_status(path, *a, **k), day=nxt.isoformat()) if path == "/svc/status" else real_status(path, *a, **k)      # 05:00: the broadcast day rolls over
    p.b.day_shows = lambda d1, d2=None: [night, at(2, 300, "06:00 bulletin")] if d1 == nxt else []; p.list_at = 0; p.cycle()
    assert set(p.c.shows) == {"200", "300"} and p.show_day["200"] == nxt.isoformat(), "now listed in the normal list of the new day: followed as before"

def test_the_status_reports_when_the_broadcast_day_ends(web):
    d = web.svc("GET", "/svc/status")[1]; ends = dt.datetime.fromisoformat(d["day_ends"]); now = dt.datetime.now(dt.timezone.utc)
    assert 0 < (ends - now).total_seconds() <= 24 * 3600 + 5

def test_day_end_carries_the_servers_time_zone(tmp_path):
    out = {}
    for tz in ("Asia/Kolkata", "Pacific/Auckland"):
        d = tmp_path / tz.replace("/", "_"); d.mkdir(); s = Srv(d, "story_id", {"AUTOID_TZ": tz}); s.login()
        r = s.svc("GET", "/svc/status")[1]; e = dt.datetime.fromisoformat(r["day_ends"]); out[tz] = e
        assert e.utcoffset() is not None and e.utcoffset() != dt.timedelta(0), "the offset of %s, not UTC" % tz
        assert e.hour == 5 and e.minute == 0 and 0 < (e - dt.datetime.now(dt.timezone.utc)).total_seconds() <= 24 * 3600 + 5, "05:00 local, within the next 24 h"

# ---------------------------------------------------------------- v9.5.2: CSV export of the day's list
import csv as _csv, io as _io, urllib.request as _ur, urllib.error as _ue

def _get_raw(web, path, cookie=True):
    req = _ur.Request("http://127.0.0.1:%d%s" % (web.port, path), headers={"Cookie": web.cookie} if (cookie and web.cookie) else {})
    try:
        with _ur.urlopen(req, timeout=10) as r: return r.status, r.read(), r.headers
    except _ue.HTTPError as e: return e.code, e.read(), e.headers

def _seed_csv(web):
    web.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "1500", "rundown_name": "News at Nine", "rundown_start": "2026-11-10T09:00:00+00:00", "stories": [
        {"blaze_story_id": "5001", "slug": "FLOOD", "slug_id": "9001", "position": 1, "story_title": "River bursts its banks"},
        {"blaze_story_id": "5002", "slug": "=HYPERLINK(\"http://x\")", "slug_id": "9002", "position": 2},
        {"blaze_story_id": "5003", "slug": "BUDGET, \"final\"", "slug_id": "9003", "position": 3}]})
    web.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "1600", "rundown_name": "Late", "stories": [{"blaze_story_id": "6001", "slug": "OTHER", "slug_id": "1", "position": 1}]})

def test_csv_export_holds_every_matching_row_not_one_page_and_is_safe_in_excel(web):
    _seed_csv(web)
    st, body, h = _get_raw(web, "/api/clips.csv?per_page=1&page=2")                                  # page parameters are ignored: it is the whole list
    assert st == 200 and h["Content-Type"].startswith("text/csv") and "attachment" in h["Content-Disposition"] and ".csv" in h["Content-Disposition"]
    assert body.startswith(b"\xef\xbb\xbf"), "a BOM so Excel reads the UTF-8"
    rows = list(_csv.reader(_io.StringIO(body.decode("utf-8-sig")))); assert rows[0][:4] == ["Clip ID", "State", "Version", "Slug"] and len(rows) == 5
    by = {r[8]: r for r in rows[1:]}
    assert by["5001"][4] == "River bursts its banks" and by["5001"][5] == "News at Nine" and by["5001"][7] == "1500" and by["5001"][9] == "9001" and by["5001"][1] == "WAITING_FOR_CLIP"
    assert by["5002"][3].startswith("'=HYPERLINK"), "a slug that starts with = is written as text, never run as a formula"
    assert by["5003"][3] == 'BUDGET, "final"', "commas and quotes survive"
    import datetime as dt
    assert by["5001"][6] == dt.datetime.fromisoformat("2026-11-10T09:00:00+00:00").astimezone().strftime("%H:%M")

def test_csv_export_follows_search_filter_and_show_and_needs_a_login_and_is_logged(web):
    _seed_csv(web)
    ids = lambda path: sorted(r[8] for r in list(_csv.reader(_io.StringIO(_get_raw(web, path)[1].decode("utf-8-sig"))))[1:])
    assert ids("/api/clips.csv?q=river") == ["5001"] and ids("/api/clips.csv?show=1600") == ["6001"] and ids("/api/clips.csv?filter=nitro") == [] and len(ids("/api/clips.csv")) == 4
    assert _get_raw(web, "/api/clips.csv", cookie=False)[0] == 401
    ev = web.call("GET", "/api/events")[1]; ev = ev if isinstance(ev, list) else ev.get("events", ev)
    assert any("clips_exported" in str(e) for e in ev), "every export is in the activity log"

# ---------------------------------------------------------------- v9.6: BLAZE_VERSION_MODE (desk | auto)
from test_blaze_poll import live_env, ready_clip, posts, set_state, media, watch_lines, env, slug                # noqa: F401

def _version_world(tmp_path, **extra):
    """A live poller; clip v1 attached by the tool; the desk has pressed + Version; the _V2 file is on Nitro and in Blaze's media list."""
    s, f, p, e = live_env(tmp_path, **extra); did = ready_clip(s, f, p); p.cycle(); p.cycle()
    assert len(posts(f)) == 1 and f.story_clips["724921"] and f.story_clips["724921"][0][0] == 1103586, "v1 attached"
    s.login(); row = [c for c in s.call("GET", "/api/clips")[1]["clips"] if c["display_id"] == did][0]
    v2 = s.call("POST", "/api/clips/%d/version" % row["id"])[1]["display_id"]; assert v2.endswith("_V2")
    set_state(s, v2, "ON_NITRO"); f.medias.append(media(1103999, v2[:14] + "_SVO_V2.mxf")); return s, f, p, e, did, v2

def _state(s, did): return [r for r in clips(s) if r["display_id"] == did][0]

def test_version_mode_desk_is_the_default_and_a_new_version_is_never_attached_by_the_tool(tmp_path):
    s, f, p, e, did, v2 = _version_world(tmp_path)
    assert p.c.version_mode == "desk"
    for _ in range(4): p.cycle()
    assert len(posts(f)) == 1 and [m for m, _ in f.story_clips["724921"]] == [1103586] and not [x for x in f.log if x[0] == "DELETE"], "nothing sent for version 2, nothing deleted"
    L = watch_lines(p); assert any("NEW VERSION READY" in x and v2 in x and "BLAZE_VERSION_MODE=desk" in x for x in L)
    r = _state(s, v2); assert r["state"] == "NEEDS_DESK"
    s.login(); shown = [c for c in s.call("GET", "/api/clips")[1]["clips"] if c["display_id"] == v2][0]; assert "New version ready" in (shown["error"] or ""), "the desk sees it on the card"
    p2 = bp.Poller(p.c); p2.cycle(); assert len(posts(f)) == 1, "a restart changes nothing"

def test_version_mode_auto_attaches_the_new_version_first_then_removes_the_old_clip(tmp_path):
    s, f, p, e, did, v2 = _version_world(tmp_path, BLAZE_VERSION_MODE="auto")
    for _ in range(4): p.cycle()
    assert len(posts(f)) == 2 and [m for m, _ in f.story_clips["724921"]] == [1103999], "the story holds exactly the new version's file"
    order = [x[0] for x in f.log if (x[0] == "POST" and "/clips/" in x[1]) or x[0] == "DELETE"]; assert order == ["POST", "POST", "DELETE"], "attach before delete, never the other way round: %s" % order
    L = watch_lines(p); assert any("REPLACED" in x and v2 in x for x in L) and any("REMOVING OLD VERSION" in x for x in L) and any("DURATION" in x for x in L)
    assert _state(s, v2)["state"] == "ATTACHED" and p.led.get("replace:" + v2) == "done"
    n = len(f.log); p.cycle(); p.cycle(); assert not [x for x in f.log[n:] if x[0] in ("POST", "DELETE") and "/clips/" in x[1]], "once only"
    p2 = bp.Poller(p.c); p2.cycle(); assert len(posts(f)) == 2 and len([x for x in f.log if x[0] == "DELETE"]) == 1, "a restart does not repeat either call"

def test_version_mode_auto_in_dry_run_only_says_what_it_would_do(env):
    s, f, p = env; assert p.c.attach == "dry"; p.c.version_mode = "auto"
    f.slugs = [slug(724921, "AUTO ID 05", 14, 20)]; p.cycle(); did = [r for r in clips(s) if r["blaze_story_id"] == "724921"][0]["display_id"]
    s.login(); rid = [c for c in s.call("GET", "/api/clips")[1]["clips"] if c["display_id"] == did][0]["id"]; v2 = s.call("POST", "/api/clips/%d/version" % rid)[1]["display_id"]
    set_state(s, v2, "ON_NITRO"); f.story_clips["724921"] = [(1103586, did[:14] + "_SVO.mxf")]; f.medias.append(media(1103999, v2[:14] + "_SVO_V2.mxf")); p = bp.Poller(p.c); p.c.version_mode = "auto"; p.cycle(); p.cycle()      # a new poller: no cached media answers
    L = watch_lines(p); assert any("REPLACES version 1" in x and "DRY RUN" in x for x in L) and any("DELETE /DataService/stories/724921/clips/" in x for x in L)
    assert not posts(f) and not [x for x in f.log if x[0] == "DELETE"], "dry run sends nothing"

def test_a_refused_attach_never_deletes_the_old_version(tmp_path):
    s, f, p, e, did, v2 = _version_world(tmp_path, BLAZE_VERSION_MODE="auto"); f.post_mode = "refuse"
    for _ in range(3): p.cycle()
    assert [m for m, _ in f.story_clips["724921"]] == [1103586] and not [x for x in f.log if x[0] == "DELETE"], "the story keeps its clip"
    assert _state(s, v2)["state"] == "NEEDS_DESK"

def test_a_failed_delete_leaves_both_clips_alerts_the_desk_and_is_not_repeated(tmp_path):
    s, f, p, e, did, v2 = _version_world(tmp_path, BLAZE_VERSION_MODE="auto")
    def no_delete(story, clip): raise bp.BlazeError(500, "boom")
    p.b.delete_clip = no_delete; p.cycle(); p.cycle(); p.cycle()
    assert sorted(m for m, _ in f.story_clips["724921"]) == [1103586, 1103999], "both clips stay: the safe side"
    L = watch_lines(p); assert any("REPLACE INCOMPLETE" in x and "remove clip" in x for x in L) and p.led.get("replace:" + v2).startswith("INCOMPLETE")
    assert len(posts(f)) == 2, "the attach was not repeated"

def test_the_kill_switch_between_attach_and_delete_keeps_the_old_clip(tmp_path):
    s, f, p, e, did, v2 = _version_world(tmp_path, BLAZE_VERSION_MODE="auto"); real = p.b.attach
    def attach_then_stop(*a, **k): r = real(*a, **k); pathlib.Path(p.c.stopfile).write_text("stop\n"); return r
    p.b.attach = attach_then_stop; p.cycle(); p.cycle()
    assert sorted(m for m, _ in f.story_clips["724921"]) == [1103586, 1103999] and not [x for x in f.log if x[0] == "DELETE"]
    assert any("REPLACE INCOMPLETE" in x and "kill switch" in x for x in watch_lines(p))

def test_two_older_versions_in_the_story_are_left_to_the_desk(tmp_path):
    s, f, p, e, did, v2 = _version_world(tmp_path, BLAZE_VERSION_MODE="auto")
    f.story_clips["724921"].append((1103500, did[:14] + "_SVO_V1.mxf")); p.cycle(); p.cycle()
    assert not [x for x in f.log if x[0] == "DELETE"] and len(posts(f)) == 1
    assert any("older versions of this clip" in x and "NOT SENT" in x for x in watch_lines(p))

def test_the_setting_is_checked():
    with pytest.raises(SystemExit): bp.Cfg({"BLAZE_SHOW_IDS": "1", "BLAZE_VERSION_MODE": "maybe"})
    assert bp.Cfg({"BLAZE_SHOW_IDS": "1", "BLAZE_VERSION_MODE": "AUTO"}).version_mode == "auto" and bp.Cfg({"BLAZE_SHOW_IDS": "1"}).version_mode == "desk"

def test_a_clip_and_its_new_version_are_both_searched_in_blaze_in_the_same_pass(tmp_path):
    """They share the date+number prefix of the clip ID: an earlier build keyed the parallel searches by that prefix and dropped one of the two."""
    s, f, p, e, did, v2 = _version_world(tmp_path); p.c.media_mode = "search"        # this is about the per-clip title search (BLAZE_MEDIA_MODE=search and the fallback of list mode)
    p.rows = p.fetch_rows(); p.mcache.clear(); n = len([x for x in f.log if "/mosobjects" in x[1]]); p.prefetch_media([r for r in p.rows if r["display_id"] in (did, v2)])
    assert len([x for x in f.log if "/mosobjects" in x[1]]) - n == 2, "two rows, two searches"
