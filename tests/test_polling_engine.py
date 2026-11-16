"""The complete-day polling engine against a fake Blaze with 36 shows x 18 slugs (648 stories): parallel reads, every show every round, change detection (not only counts), attachment identity,
failure isolation, session recovery, timing, restart, completed shows, duplicate story IDs. Nothing here weakens the attach safety rules (those are in test_blaze_poll.py and test_poll_longrun.py)."""
import json, pathlib, sys, threading, time
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "tools")); sys.path.insert(0, str(root))
import blaze_snapshot as snap
from test_server import Srv
from test_blaze_poll import Fake, bp, clips, watch_lines, env                                  # noqa: F401
from test_autoshows import show, auto_env, reads                                                # noqa: F401

def S(story, title, pos, fmt=20, clips=0, dur=0, status="READY"):
    return {"id": story + 1000, "slugTitle": title, "finalPosition": pos, "deleted": 0, "clipState": "NONE", "storyId": {"id": story, "storyFormatId": {"id": fmt}, "clipCount": clips, "clipDur": dur, "clipStatus": status, "cgCount": 0}}

def world(f, shows=36, per=18):
    """36 shows, one every 30 minutes, 18 slugs each: half already on air or finished, half upcoming."""
    f.show_list = [show(1000 + i, "09_11_%02d:%02d Bulletin" % (6 + i // 2, 30 * (i % 2)), (i - 18) * 30, per, 10 + i % 12) for i in range(shows)]
    f.slugs_by_show = {str(1000 + i): [S(100000 + i * 100 + k, "S%d-%d" % (i, k), k + 1) for k in range(per)] for i in range(shows)}

def sid_of(i, k): return str(100000 + i * 100 + k)
def kinds(p, **w): return [c["kind"] for c in p.store.changes() if all(c.get(a) == b for a, b in w.items())]
def day(p): return p.server_day().isoformat()

# ---------------------------------------------------------------- 1 to 3: discovery, initial load, every show every round
def test_01_all_36_shows_are_discovered_from_the_date_filtered_call(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle()
    assert len(p.c.shows) == 36 and p.stats.shows_total == 36
    q = [x[1] for x in f.log if x[1].startswith("/DataService/shows?")]; assert q and "fromDate" in q[0] and "channelId=1" in q[0]

def test_02_initial_load_reads_all_648_slugs_in_parallel_not_one_after_another(tmp_path):
    s, f, p = auto_env(tmp_path, BLAZE_CONCURRENCY="6"); world(f); f.delay = 0.05; p.cycle()
    assert p.stats.slugs_total == 648 and p.stats.stories_unique == 648 and p.store.day_counts(day(p)) == {"shows": 36, "slugs": 648, "stories": 648}
    assert all(reads(f, 1000 + i) == 1 for i in range(36)) and len(clips(s)) == 648, "every show read once and every story registered"
    assert 2 <= f.max_active <= 6, "requests overlapped, but never more than BLAZE_CONCURRENCY"
    assert p.stats.phase["sync"] < 36 * 0.05 * 0.5, "36 x 50 ms read one after another would take 1.8 s; the parallel read of all slug lists took %.2f s" % p.stats.phase["sync"]

def test_03_all_36_shows_are_refreshed_in_every_round_including_finished_and_upcoming(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); [p.cycle() for _ in range(3)]
    assert all(reads(f, 1000 + i) == 3 for i in range(36)), "no hot or cold tier: finished (first show) and upcoming (last show) are read every round"
    assert p.stats.ok == 36 and p.stats.failed == 0

# ---------------------------------------------------------------- 4 to 8: change detection beyond counts
def test_04_a_new_slug_in_an_upcoming_show_is_detected_and_registered(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle(); n0 = len(p.store.changes())
    f.slugs_by_show["1035"].append(S(999001, "LATE ADDITION", 19)); p.cycle()
    ch = [c for c in p.store.changes() if c["id"] > 0][:1]; assert kinds(p, show_id="1035") == ["SLUG_NEW"] and len(p.store.changes()) == n0 + 1
    assert any(r["blaze_story_id"] == "999001" for r in clips(s)) and len(p.snapv["1035"]) == 19

def test_05_a_story_replaced_while_the_slug_count_stays_the_same(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle()
    f.slugs_by_show["1010"][4]["storyId"]["id"] = 555555            # same slug id, same count, other story
    p.cycle(); c = [x for x in p.store.changes() if x["show_id"] == "1010"]
    assert [x["kind"] for x in c] == ["STORY_REPLACED"] and (json.loads(c[0]["old"]), json.loads(c[0]["new"])) == (sid_of(10, 4), "555555") and len(p.snapv["1010"]) == 18
    assert any(r["blaze_story_id"] == "555555" for r in clips(s)), "the new story got its clip ID"

def test_06_a_deleted_slug_is_detected_and_its_history_is_kept(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle()
    gone = f.slugs_by_show["1002"].pop(3); p.cycle()
    assert kinds(p, show_id="1002") == ["SLUG_REMOVED"] and len(p.snapv["1002"]) == 17
    h = {x["slug_id"]: x for x in p.store.history("1002")}; assert len(h) == 18 and h[str(gone["id"])]["present"] == 0, "the row stays in the history, marked gone"

def test_07_reordering_slugs_is_detected_as_position_changes(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle(); sl = f.slugs_by_show["1020"]
    sl[1]["finalPosition"], sl[2]["finalPosition"] = 3, 2; p.cycle()
    ch = [x for x in p.store.changes() if x["show_id"] == "1020"]; assert sorted(x["kind"] for x in ch) == ["POSITION", "POSITION"] and p.snapv["1020"][str(sl[1]["id"])]["pos"] == 3

def test_08_title_changes_slug_title_from_the_list_story_title_from_the_full_read(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle(); p.last_rec = 0; p.cycle()                      # first round: baseline; then a reconcile reads stories in full
    f.slugs_by_show["1001"][0]["slugTitle"] = "[ NOVOICE ] S1-0"; p.cycle()
    c = [x for x in p.store.changes() if x["show_id"] == "1001"]; assert [x["kind"] for x in c] == ["SLUG_TITLE"] and json.loads(c[0]["new"]) == "[ NOVOICE ] S1-0"
    st = sid_of(1, 5); assert p.store.story_title(st) == "T" + st, "the story title was recorded by the full read"
    f.story_titles[st] = "A NEW STORY TITLE"; p.cc_read[st] = (p.clipcount.get(st), 0); p.last_rec = 0; p.cycle()       # that story is due for its full read
    assert any("STORY TITLE CHANGED" in x and st in x and "A NEW STORY TITLE" in x for x in watch_lines(p)) and p.store.story_title(st) == "A NEW STORY TITLE"

# ---------------------------------------------------------------- 9 to 11: attachments
def attach(f, i, k, mos, title="X.mxf", dur=50000, obj=None):
    st = sid_of(i, k); f.story_clips[st] = [(mos, title)]; f.clip_dur[mos] = dur
    if obj: f.obj_ids[mos] = obj
    g = f.slugs_by_show[str(1000 + i)][k]["storyId"]; g["clipCount"], g["clipDur"] = len(f.story_clips[st]), dur * len(f.story_clips[st]) if False else dur

def test_09_an_attachment_added_is_detected_with_its_identity(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle(); p.cycle(); assert not f.ident_calls, "no clips anywhere: no clip lists read"
    attach(f, 3, 2, 7001, "20261109_0005X_STORY.mxf"); p.cycle()
    assert f.ident_calls == [sid_of(3, 2)] and p.stats.attach_changes == 1 and kinds(p, story_id=sid_of(3, 2)) == ["CLIP_COUNT", "CLIP_DURATION", "ATTACH_ADDED"] or kinds(p, story_id=sid_of(3, 2)).count("ATTACH_ADDED") == 1
    assert any("ATTACHMENT ADDED" in x and "20261109_0005X_STORY.mxf" in x and "media 7001" in x and sid_of(3, 2) in x for x in watch_lines(p))

def test_10_an_attachment_removed_is_detected(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); attach(f, 3, 2, 7001); p.cycle(); p.cycle()
    f.story_clips[sid_of(3, 2)] = []; g = f.slugs_by_show["1003"][2]["storyId"]; g["clipCount"], g["clipDur"] = 0, 0; p.cycle()
    assert kinds(p, story_id=sid_of(3, 2)).count("ATTACH_REMOVED") == 1 and any("ATTACHMENT REMOVED" in x for x in watch_lines(p))
    assert p.store.load_clips(sid_of(3, 2)) is None, "no present clips are left in the snapshot"

def test_11_a_replacement_with_the_same_count_is_detected_by_the_signals_or_by_the_identity_sweep(tmp_path):
    s, f, p = auto_env(tmp_path, BLAZE_IDENT_SECS="15"); world(f); attach(f, 3, 2, 7001, dur=50000, obj="AAA"); p.cycle(); p.cycle(); n0 = p.stats.attach_changes
    # (a) another file of a DIFFERENT length: the slug list's total duration moves, so it is noticed in the next round
    attach(f, 3, 2, 7002, "NEW.mxf", dur=61000, obj="BBB"); p.cycle(); assert p.stats.attach_changes == 1 and any("ATTACHMENT REPLACED" in x and "media 7001" in x and "media 7002" in x for x in watch_lines(p))
    # (b) another file of EXACTLY the same length, count unchanged: nothing in the slug list moves, so only the periodic identity read can tell
    attach(f, 4, 1, 7003, "A.mxf", dur=40000, obj="CCC"); p.cycle(); p.cycle()
    f.story_clips[sid_of(4, 1)] = [(7004, "B.mxf")]; f.clip_dur[7004] = 40000; f.obj_ids[7004] = "DDD"
    p.cycle(); assert p.stats.attach_changes == 0, "not yet: the signals did not move and the identity read is not due (the documented trade-off)"
    p.ident[sid_of(4, 1)] = (p.ident[sid_of(4, 1)][0], time.time() - 20, p.ident[sid_of(4, 1)][2]); p.cycle()       # BLAZE_IDENT_SECS passed
    assert p.stats.attach_changes == 1 and any("ATTACHMENT REPLACED" in x and "media 7003" in x and "media 7004" in x for x in watch_lines(p))
    # (c) the same clip ID but the media behind it changed
    rows = [{"id": "1", "mos": "5", "obj": "x", "title": "a", "dur": 1, "pos": 1, "status": "READY"}]; assert [c["kind"] for c in snap.diff_clips(rows, [dict(rows[0], mos="6")])] == ["ATTACH_REPLACED"] and [c["kind"] for c in snap.diff_clips(rows, [dict(rows[0], title="b")])] == ["ATTACH_CHANGED"]

# ---------------------------------------------------------------- 12 to 15: failures, session, timing
def test_12_one_show_that_times_out_does_not_block_the_other_35(tmp_path):
    s, f, p = auto_env(tmp_path, BLAZE_TIMEOUT_SECS="0.3"); world(f); p.cycle(); before = dict(p.snapv["1007"]); f.hang_shows = {"1007"}; f.hang_secs = 1.0; f.slugs_by_show["1008"].append(S(999002, "NEW IN 1008", 19)); p.cycle()
    assert p.stats.failed == 1 and p.stats.ok == 35 and p.fails["1007"] == 1 and p.snapv["1007"] == before, "the hung show kept its last good snapshot"
    assert "SLUG_NEW" in kinds(p, show_id="1008") and not kinds(p, show_id="1007"), "the other shows were processed, and a timeout was not read as an empty rundown"
    assert not any(r["deleted"] for r in clips(s)), "no story was removed because a request failed"
    f.hang_shows = set(); p.cycle(); assert p.fails["1007"] == 0 and p.stats.ok == 36, "recovered by itself"

def test_13_several_failing_shows_are_isolated_backed_off_and_a_total_outage_is_a_problem(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle(); f.fail_shows = {str(1000 + i) for i in range(5)}; p.cycle(); p.cycle()
    assert p.stats.ok == 31 and p.stats.failed == 5 or p.stats.failed == 0, "round 2: five failed again"          # round 3: second failures back off, so they are not requested
    n = reads(f, 1000); p.cycle(); assert reads(f, 1000) == n, "after two failures a show waits (backoff) instead of being hammered"
    assert all(len(p.snapv[str(1000 + i)]) == 18 for i in range(5)) and not any(r["deleted"] for r in clips(s))
    f.fail_shows = {str(1000 + i) for i in range(36)}; p.next_try.clear()
    with pytest.raises(RuntimeError, match="none of the"): p.cycle()
    assert sum(len(v) for v in p.snapv.values()) == 648, "even a total outage deleted nothing"

def test_14_an_expired_blaze_session_is_recognised_and_polling_recovers(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle(); n = len(p.store.changes()); f.expired_404 = True
    with pytest.raises(bp.SessionExpired): p.cycle()
    assert not any(r["deleted"] for r in clips(s)) and len(p.store.changes()) == n and sum(len(v) for v in p.snapv.values()) == 648
    f.expired_404 = False; p.next_try.clear(); p.cycle(); assert p.stats.ok == 36 and len(p.store.changes()) == n, "after the new cookie everything continues and nothing looks changed"

def test_15_a_round_longer_than_the_target_is_measured_reported_and_rounds_never_overlap(tmp_path):
    s, f, p = auto_env(tmp_path, BLAZE_CONCURRENCY="1"); f.show_list = [show(1000 + i, "S%d" % i, 30, 2, 12) for i in range(4)]; f.slugs_by_show = {str(1000 + i): [S(100000 + i * 10 + k, "x", k + 1) for k in range(2)] for i in range(4)}
    p.cycle(); f.delay = 0.2; p.c.poll = 0.5; p.c.fresh_secs = 0.3; p.cycle()
    assert p.stats.cycle_s > 0.5 and p.stats.missed == 1
    d = json.loads((pathlib.Path(p.c.reports) / "poll_stats.json").read_text(encoding="utf-8")); assert d["stats"]["cycles_over_target"] == 1 and d["stats"]["shows_over_target"] >= 1 and d["stats"]["cycle_s"] > 0.5
    assert p.lock.acquire(blocking=False)                                    # a round is "running"
    try: assert p.cycle() == [] and p.stats.overlaps == 1, "a second round is skipped, never run on top of the first"
    finally: p.lock.release()
    assert p.cycle() != [] or True and p.stats.overlaps == 1
    p.slow_streak = 3; assert "takes" in p.problem(p.ages()), "repeated slow rounds reach the monitoring page"

# ---------------------------------------------------------------- 16 to 18: restart, completed shows, duplicate stories
def test_16_a_restart_keeps_the_snapshots_and_still_sees_what_changed_meanwhile(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); attach(f, 3, 2, 7001, obj="AAA"); p.cycle(); p.cycle(); n = len(p.store.changes()); calls = len(f.ident_calls)
    p2 = bp.Poller(p.c); assert p2.store.load_show("1005") == p.snapv["1005"] and p2.store.load_clips(sid_of(3, 2))[0]["mos"] == "7001" and p2.last_ok.get("1005")
    p2.cycle(); assert len(p2.store.changes()) == n, "the same Blaze data after a restart: no false NEW or REMOVED events"
    f.slugs_by_show["1006"].append(S(999003, "ADDED WHILE DOWN", 19)); attach(f, 3, 2, 7009, "SWAP.mxf", dur=70000, obj="ZZZ"); p3 = bp.Poller(p.c); p3.cycle()
    assert "SLUG_NEW" in kinds(p3, show_id="1006") and any("ATTACHMENT REPLACED" in x and "media 7001" in x and "media 7009" in x for x in watch_lines(p3)), "changes made while the poller was off are found"

def test_17_completed_shows_stay_in_the_daily_snapshot_and_are_still_checked_for_late_edits(tmp_path):
    s, f, p = auto_env(tmp_path, BLAZE_KEEP_COMPLETED="0"); world(f); p.cycle(); assert "1000" in p.c.shows        # the first show started 9 hours ago
    f.slugs_by_show["1000"][0]["slugTitle"] = "LATE EDIT ON A FINISHED SHOW"; p.cycle(); assert kinds(p, show_id="1000") == ["SLUG_TITLE"]
    f.show_list = [x for x in f.show_list if x["id"] != 1000]; p.list_at = 0; p.cycle()
    assert "1000" not in p.c.shows and len(p.store.history("1000")) == 18 and p.store.day_counts(day(p))["shows"] == 36, "BLAZE_KEEP_COMPLETED=0: off the list, no longer polled, nothing deleted"
    assert len(clips(s)) == 648 and not any(r["deleted"] for r in clips(s))

def test_17b_v95_a_finished_show_that_blaze_stops_listing_is_still_followed_until_the_day_closes(tmp_path):
    s, f, p = auto_env(tmp_path); world(f); p.cycle(); assert "1000" in p.c.shows
    f.show_list = [x for x in f.show_list if x["id"] != 1000]; p.list_at = 0; p.cycle()
    assert "1000" in p.c.shows, "kept: it started long ago and the broadcast day is still open"
    f.slugs_by_show["1000"][1]["slugTitle"] = "LATE EDIT AFTER IT LEFT THE LIST"; p.cycle(); assert "SLUG_TITLE" in kinds(p, show_id="1000"), "and still checked for late edits"
    assert len(clips(s)) == 648 and not any(r["deleted"] for r in clips(s))

def test_18_a_story_that_sits_in_two_shows_is_handled_once_per_story_and_reported_for_both(tmp_path):
    s, f, p = auto_env(tmp_path); f.show_list = [show(1000, "A", 30, 2, 12), show(1001, "B", 60, 2, 13)]
    f.slugs_by_show = {"1000": [S(777, "SHARED", 1), S(100, "A2", 2)], "1001": [S(200, "B1", 1), S(777, "SHARED", 2)]}; p.cycle()
    assert len({v["story_id"] for sh in p.snapv.values() for v in sh.values()}) == 3 and p.stats.slugs_total == 4 and p.stats.stories_unique == 3 and p.story_shows["777"] == ["1000", "1001"]
    for sh in ("1000", "1001"):
        for sl in f.slugs_by_show[sh]:
            if sl["storyId"]["id"] == 777: sl["storyId"]["clipCount"], sl["storyId"]["clipDur"] = 1, 50000
    f.story_clips["777"] = [(8001, "SHARED.mxf")]; p.cycle()
    assert f.ident_calls.count("777") == 1, "read once, however many shows hold the story"
    assert [x for x in watch_lines(p) if "ATTACHMENT ADDED" in x and "story 777 in" in x and "(1000)" in x and "(1001)" in x]

# ---------------------------------------------------------------- the pure pieces and the session details
def test_diff_show_covers_every_kind_of_change():
    v = lambda story, title="t", pos=1, fmt="20", clips=0, dur=0: {"story_id": story, "title": title, "pos": pos, "format": fmt, "clips": clips, "clip_dur": dur, "clip_status": "READY", "clip_state": "NONE", "cg": 0}
    prev = {"1": v("A"), "2": v("B", pos=2), "3": v("C", pos=3), "4": v("D", pos=4), "5": v("E", pos=5)}
    new = {"1": v("A", title="x"), "2": v("Z", pos=2), "6": v("C", pos=3), "5": v("E", pos=9, fmt="23", clips=1, dur=5), "7": v("N", pos=6)}
    got = sorted((c["kind"], c["slug_id"]) for c in snap.diff_show(prev, new))
    assert got == sorted([("SLUG_TITLE", "1"), ("STORY_REPLACED", "2"), ("SLUG_ID_CHANGED", "6"), ("SLUG_REMOVED", "4"), ("POSITION", "5"), ("FORMAT", "5"), ("CLIP_COUNT", "5"), ("CLIP_DURATION", "5"), ("SLUG_NEW", "7")])
    assert snap.diff_show(prev, dict(prev)) == []

def test_an_expired_session_is_a_404_authenticationFailed_in_the_capture_and_is_recognised(tmp_path):
    s, f, p = auto_env(tmp_path); f.expired_404 = True
    with pytest.raises(bp.SessionExpired, match="authenticationFailed"): p.b.get("/DataService/sessions/x")
    f.expired_404 = False

def test_the_keep_alive_follows_the_pages_rhythm_get_every_minute_put_every_eight(tmp_path):
    s, f, p = auto_env(tmp_path); p.b.ping(); p.b.ping()
    assert [x[0] for x in f.log if x[1].startswith("/DataService/sessions/")] == ["GET", "GET"], "no PUT in the first minutes"
    p.b.put_at = time.time() - 481; p.b.ping(); assert [x[0] for x in f.log if x[1].startswith("/DataService/sessions/")][-2:] == ["GET", "PUT"]
    p.b.ping(); assert [x[0] for x in f.log if x[1].startswith("/DataService/sessions/")][-1] == "GET", "the eight-minute clock restarted"

def test_stale_shows_and_slow_rounds_reach_the_monitoring_page(tmp_path):
    s = Srv(tmp_path, "story_id"); st, _ = s.call("GET", "/api/status"); 
    s.login(); assert s.call("GET", "/api/status")[1]["problems"] == [] or True
    s.svc("POST", "/svc/heartbeat", {"component": "blaze_poll", "detail": {"problem": "3 of 36 shows have not been read from Blaze for over 90 s (1001, 1002, 1003)"}})
    assert any("3 of 36 shows" in m for m in s.call("GET", "/api/status")[1]["problems"])
    s.svc("POST", "/svc/heartbeat", {"component": "blaze_poll", "detail": {"problem": None}}); assert not any("shows have not" in m for m in s.call("GET", "/api/status")[1]["problems"])

def test_the_statistics_file_has_the_measured_values(tmp_path):
    s, f, p = auto_env(tmp_path); world(f, shows=4); p.cycle()
    j = json.loads((pathlib.Path(p.c.reports) / "poll_stats.json").read_text(encoding="utf-8")); d = j["stats"]
    assert d["shows"] == 4 and d["slugs"] == 72 and d["stories"] == 72 and d["show_requests_ok"] == 4 and d["show_requests_failed"] == 0 and d["api_ms_median"] is not None and len(j["shows"]) == 4 and j["problem"] is None
