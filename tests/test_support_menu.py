"""v10.10.0 Quick Support: a side menu to add a media clip to a story (picked from the list, or a typed name that is queued until the file appears) and to delete a clip from a story (Yes / No).
Nothing is sent from the page: a request is recorded with the user's name and the Blaze poller carries it out, after its normal round, under the same safety rules as a confirmed Quick test."""
import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_blaze_poll import bp, env, live_env, ready_clip, posts, watch_lines, clips, media, slug
from test_quick_test_button import dry, run

def add(s, rundown="34427", story="724921", **kw): return s.call("POST", "/api/support/add", dict({"rundown": rundown, "story": story, "confirm": True}, **kw))
def jobs(s): return s.call("GET", "/api/support/jobs")[1]["jobs"]
def job(s, jid): return s.call("GET", "/api/support/jobs/%d" % jid)[1]
def deletes(f): return [x for x in f.log if x[0] == "DELETE"]
def ready_dry(tmp_path, **kw):
    s, f, p, e = dry(tmp_path, **kw); did = ready_clip(s, f, p); run(p); return s, f, p, e, did
def state(s, did): return [x for x in clips(s) if x["display_id"] == did][0]["state"]

def test_the_pickers_show_the_bulletin_the_story_and_the_files_the_log_found(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path)
    b = s.call("GET", "/api/support/bulletins")[1]; assert [x["id"] for x in b["bulletins"]] == ["34427"] and b["bulletins"][0]["stories"] == 1 and b["wait_min"] == 60
    st = s.call("GET", "/api/support/stories?rundown=34427")[1]["stories"]; assert [x["id"] for x in st] == ["724921"] and st[0]["title"] == "AUTO ID 05"
    m = s.call("GET", "/api/support/media")[1]["media"]; assert [x["media_id"] for x in m] == ["1103586"] and m[0]["name"]

def test_nothing_is_queued_without_yes_and_a_bad_name_is_refused(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path)
    assert s.call("POST", "/api/support/add", {"rundown": "34427", "story": "724921", "media_id": "1103586"})[0] == 400
    assert add(s, media_id="1103586", name="X_Y")[0] == 400, "a pick and a typed name together"
    st, body = add(s, name="hello world"); assert st == 422 and "DDMMYY_STORY_NAME" in str(body)
    assert add(s, story="1")[0] in (400, 404) and add(s, rundown="nope", media_id="1103586")[0] == 404
    assert s.call("POST", "/api/support/remove", {"rundown": "34427", "story": "724921", "clip_id": "1"})[0] == 400
    run(p); assert not jobs(s) and not posts(f)

def test_a_picked_clip_is_attached_once_even_in_dry_mode(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); assert not posts(f)
    st, body = add(s, media_id="1103586"); assert st == 200; jid = body["id"]
    assert job(s, jid)["state"] == "QUEUED" and job(s, jid)["by_user"]
    run(p); assert [x["mosObjectId"] for x in posts(f)] == ["1103586"]
    j = job(s, jid); assert j["state"] == "DONE" and "Attached" in j["msg"] and state(s, did) == "ATTACHED"
    run(p); assert len(posts(f)) == 1, "never twice"
    assert any("SUPPORT ADD" in x and "sending now" in x for x in watch_lines(p))
    st, body = add(s, media_id="1103586"); assert st == 200; run(p)                     # asked again: the file is already in the story, nothing is sent
    assert len(posts(f)) == 1 and "already in the story" in job(s, body["id"])["msg"]

def test_a_typed_name_waits_for_the_file_then_attaches_and_everyone_can_see_it(env, tmp_path):
    s, f, p, e = dry(tmp_path); f.slugs = f.slugs + [slug(724921, "AUTO ID 05", 14, 20)]; p.cycle()
    did = [x for x in clips(s) if x["blaze_story_id"] == "724921"][0]["display_id"]
    st, body = add(s, name=did[:14] + "_SVO"); assert st == 200; jid = body["id"]
    run(p); j = job(s, jid); assert j["state"] == "QUEUED" and "waiting" in j["msg"].lower() and not posts(f)
    f.medias.append(media(1103586, did[:14] + "_SVO.mxf")); run(p)
    assert job(s, jid)["state"] == "DONE" and [x["mosObjectId"] for x in posts(f)] == ["1103586"] and state(s, did) == "ATTACHED"
    assert [x["id"] for x in jobs(s)] == [jid], "the finished request stays visible to everyone for a day"

def test_a_file_still_being_converted_is_waited_for(env, tmp_path):
    s, f, p, e = dry(tmp_path); f.slugs = f.slugs + [slug(724921, "AUTO ID 05", 14, 20)]; p.cycle()
    did = [x for x in clips(s) if x["blaze_story_id"] == "724921"][0]["display_id"]; f.medias.append(media(1103586, did[:14] + "_SVO.mxf", secs_ago=5))      # changed 5 s ago: still settling
    jid = add(s, name=did[:14])[1]["id"]; run(p); assert job(s, jid)["state"] == "QUEUED" and not posts(f)

def test_a_request_whose_file_never_comes_expires_and_sends_nothing(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); jid = add(s, name="221126_NEVER_COMES")[1]["id"]; run(p); assert job(s, jid)["state"] == "QUEUED"
    with s.app.db.tx() as cur: cur.x("UPDATE support_jobs SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (jid,))
    run(p); j = job(s, jid); assert j["state"] == "EXPIRED" and "did not appear" in j["msg"] and not posts(f)
    with s.app.db.tx() as cur: assert cur.one("SELECT 1 FROM events WHERE action='support_expired'")

def test_a_queued_request_can_be_cancelled_but_not_one_that_has_run(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); a = add(s, name="221126_LATER")[1]["id"]; assert s.call("POST", "/api/support/jobs/%d/cancel" % a)[0] == 200 and job(s, a)["state"] == "CANCELLED"
    run(p); assert not posts(f); b = add(s, media_id="1103586")[1]["id"]; run(p); st, body = s.call("POST", "/api/support/jobs/%d/cancel" % b); assert st == 409 and job(s, b)["state"] == "DONE"

def test_the_same_clip_cannot_be_queued_twice_for_a_story(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); assert add(s, name="221126_TWICE")[0] == 200; st, body = add(s, name="221126_twice"); assert st == 409 and "already queued" in str(body)

def test_safety_rules_still_apply_kill_switch_unverified_format_and_off(env, tmp_path):
    (tmp_path / "k").mkdir(); s, f, p, e, did = ready_dry(tmp_path / "k"); (tmp_path / "k" / "STOP_LIVE").write_text("stop"); jid = add(s, media_id="1103586")[1]["id"]; run(p)
    assert job(s, jid)["state"] == "BLOCKED" and "kill switch" in job(s, jid)["msg"] and not posts(f)
    (tmp_path / "v").mkdir(); s, f, p, e = dry(tmp_path / "v"); did = ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 23); run(p); jid = add(s, media_id="1103586")[1]["id"]; run(p)
    assert job(s, jid)["state"] == "BLOCKED" and "not verified" in job(s, jid)["msg"] and not posts(f)
    (tmp_path / "o").mkdir(); s, f, p, e = live_env(tmp_path / "o", BLAZE_ATTACH="off", BLAZE_LIVE_SHOW_IDS=""); assert s.login()[0] == 200; did = ready_clip(s, f, p); jid = add(s, name=did[:14])[1]["id"]; run(p); assert job(s, jid)["state"] == "BLOCKED" and "BLAZE_ATTACH=off" in job(s, jid)["msg"] and not posts(f)

def test_a_bulletin_the_poller_does_not_follow_is_blocked(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); p.c.shows[:] = ["99999"]; jid = add(s, media_id="1103586")[1]["id"]; run(p); assert job(s, jid)["state"] == "BLOCKED" and "does not follow" in job(s, jid)["msg"] and not posts(f)

def test_two_files_with_the_same_name_are_not_guessed(env, tmp_path):
    s, f, p, e = dry(tmp_path); f.slugs = f.slugs + [slug(724921, "AUTO ID 05", 14, 20)]; p.cycle(); did = [x for x in clips(s) if x["blaze_story_id"] == "724921"][0]["display_id"]
    f.medias += [media(1103586, did[:14] + "_A.mxf"), media(1103587, did[:14] + "_B.mxf")]; jid = add(s, name=did[:14])[1]["id"]; run(p); j = job(s, jid)
    assert j["state"] == "BLOCKED" and "2 Blaze files" in j["msg"] and not posts(f)

def attached(tmp_path, live=False):
    s, f, p, e = (live_env(tmp_path) if live else dry(tmp_path)); assert s.login()[0] == 200; did = ready_clip(s, f, p); run(p)
    if not live: add(s, media_id="1103586"); run(p)
    assert len(posts(f)) == 1 and state(s, did) == "ATTACHED"; return s, f, p, e, did
def clip_list(s, p, story="724921"):
    jid = s.call("POST", "/api/support/list", {"rundown": "34427", "story": story})[1]["id"]; run(p, 1); j = job(s, jid); assert j["state"] == "DONE", j; return j["result"]

def test_delete_lists_the_clips_blaze_holds_then_deletes_only_after_yes(env, tmp_path):
    s, f, p, e, did = attached(tmp_path); r = clip_list(s, p); assert len(r["clips"]) == 1 and r["clips"][0]["mos"] == "1103586" and r["shows"] == ["34427"]; c = r["clips"][0]
    assert s.call("POST", "/api/support/remove", {"rundown": "34427", "story": "724921", "clip_id": str(c["id"]), "clip_title": c["title"]})[0] == 400; run(p); assert not deletes(f)
    st, body = s.call("POST", "/api/support/remove", {"rundown": "34427", "story": "724921", "clip_id": str(c["id"]), "clip_title": c["title"], "confirm": True}); assert st == 200
    run(p); assert len(deletes(f)) == 1 and job(s, body["id"])["state"] == "DONE" and "Deleted" in job(s, body["id"])["msg"]
    assert clip_list(s, p)["clips"] == []; run(p); assert len(deletes(f)) == 1, "never twice"
    st, body = s.call("POST", "/api/support/remove", {"rundown": "34427", "story": "724921", "clip_id": str(c["id"]), "clip_title": c["title"], "confirm": True}); run(p)
    assert job(s, body["id"])["state"] == "DONE" and "not in the story any more" in job(s, body["id"])["msg"] and len(deletes(f)) == 1

def test_a_deleted_clip_is_not_attached_again_by_the_automatic_attach(env, tmp_path):
    s, f, p, e, did = attached(tmp_path, live=True); c = clip_list(s, p)["clips"][0]
    jid = s.call("POST", "/api/support/remove", {"rundown": "34427", "story": "724921", "clip_id": str(c["id"]), "clip_title": c["title"], "confirm": True})[1]["id"]; run(p)
    assert job(s, jid)["state"] == "DONE" and len(deletes(f)) == 1
    run(p, 5); assert len(posts(f)) == 1, "the automatic attach must not put it back"
    row = [x for x in clips(s) if x["display_id"] == did][0]; assert row["state"] == "NEEDS_DESK" and "DELETED FROM THE STORY" in str(row), row; assert [x for x in s.call("GET", "/api/clips")[1]["clips"] if x["display_id"] == did][0]["mos_object_id"] == "1103586"
    st, body = add(s, media_id="1103586"); run(p); assert job(s, body["id"])["state"] == "DONE" and len(posts(f)) == 2 and state(s, did) == "ATTACHED", "Add media puts it back"

def test_a_clip_that_changed_since_the_list_is_not_deleted(env, tmp_path):
    s, f, p, e, did = attached(tmp_path); c = clip_list(s, p)["clips"][0]
    jid = s.call("POST", "/api/support/remove", {"rundown": "34427", "story": "724921", "clip_id": str(c["id"]), "clip_title": "SOMETHING ELSE", "confirm": True})[1]["id"]; run(p)
    assert job(s, jid)["state"] == "BLOCKED" and not deletes(f)

def test_a_story_in_two_bulletins_says_so_in_the_list(env, tmp_path):
    s, f, p, e, did = attached(tmp_path); f.linked["724921"] = [34428]; p.info_cache.clear(); r = clip_list(s, p); assert set(r["shows"]) == {"34427", "34428"} and len(r["show_names"]) == 2

def test_the_poller_part_never_reaches_the_round_and_costs_blaze_nothing_when_idle(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); n = len(f.log); p.support_round("ALL"); assert len(f.log) == n, "no request, no call to Blaze"
    def boom(*a, **k): raise RuntimeError("boom")
    p.support_round = boom; p.cycle()                                                                    # the round finishes whatever happens in there
    p.support_round = type(p).support_round.__get__(p); s.app.db.conn.execute("DROP TABLE support_jobs")
    p.cycle()                                                                                            # even a server that cannot answer: the round carries on

def test_a_request_that_was_working_when_the_poller_stopped_is_settled_by_reading_never_resent(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); jid = add(s, media_id="1103586")[1]["id"]
    with s.app.db.tx() as cur: cur.x("UPDATE support_jobs SET state='WORKING' WHERE id=?", (jid,))
    run(p); j = job(s, jid); assert j["state"] == "FAILED" and "unclear" in j["msg"] and not posts(f), "not in the story, and never sent again"

def test_the_list_thread_answers_without_the_round(env, tmp_path):
    s, f, p, e = dry(tmp_path); did = ready_clip(s, f, p); run(p); add(s, media_id="1103586"); run(p); p.c.support_list_secs = 0.2; p.sup_start(); assert p.sup_thread_alive()
    jid = s.call("POST", "/api/support/list", {"rundown": "34427", "story": "724921"})[1]["id"]
    for _ in range(40):
        if job(s, jid)["state"] == "DONE": break
        time.sleep(0.1)
    assert job(s, jid)["state"] == "DONE" and len(job(s, jid)["result"]["clips"]) == 1

def test_can_be_switched_off(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); s.app.cfg["support"] = False
    assert add(s, media_id="1103586")[0] == 403 and s.call("GET", "/api/support/jobs")[0] == 403 and s.call("GET", "/api/config")[1]["support"] is False

def test_the_menu_is_in_the_page_with_the_agreed_wording():
    h = (pathlib.Path(__file__).resolve().parent.parent / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    for needle in ("Quick Support", "For exceptions only.", "only when something really needs fixing", "data-tab=\"support\"", "Add media", "Delete media", "/api/support/add", "/api/support/remove", "/api/support/list",
                   "Search the clip…", "Not in the list? Type the correct name and queue it", "Yes, delete", "Yes, queue it", "The file itself stays in Nitro", "Media added: ", "supPoll"): assert needle in h, needle


# ---------------------------------------------------------------- v10.10.1: edge cases
import calendar, sqlite3


def test_an_older_support_table_from_the_worker_build_does_not_stop_the_database(tmp_path):
    from autoid_lite.db import DB
    p = tmp_path / "old.db"; c = sqlite3.connect(p)
    c.executescript("CREATE TABLE support_jobs(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL, expire_at REAL);"
                    "CREATE INDEX idx_support_status ON support_jobs(status, kind);"); c.execute("INSERT INTO support_jobs(kind,status,created_at,updated_at) VALUES('ADD','ATTACHED',1,1)"); c.commit(); c.close()
    d = DB(p)                                                                                           # used to fail: no such column: state
    cols = {r["name"] for r in d.conn.execute("PRAGMA table_info(support_jobs)").fetchall()}; assert "state" in cols and "status" not in cols
    assert d.conn.execute("SELECT COUNT(*) AS n FROM support_jobs").fetchone()["n"] == 0
    assert d.conn.execute("SELECT status FROM support_jobs_legacy").fetchone()["status"] == "ATTACHED", "the old history is kept, not deleted"
    with d.tx() as cur: cur.insert("INSERT INTO support_jobs(kind,state) VALUES('ADD','QUEUED')")
    d.conn.close(); d = DB(p)                                                                           # a second start leaves everything alone
    assert d.conn.execute("SELECT COUNT(*) AS n FROM support_jobs").fetchone()["n"] == 1 and d.conn.execute("SELECT COUNT(*) AS n FROM support_jobs_legacy").fetchone()["n"] == 1
    d.conn.close()
    q = tmp_path / "old2.db"; c = sqlite3.connect(q); c.executescript("CREATE TABLE support_jobs(id INTEGER PRIMARY KEY, status TEXT); CREATE TABLE support_jobs_legacy(x INTEGER);"); c.close()
    d = DB(q); names = {r["name"] for r in d.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}; assert {"support_jobs", "support_jobs_legacy", "support_jobs_legacy_"} <= names


def test_bad_input_gets_a_clean_answer_never_an_internal_error(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path)
    assert s.call("GET", "/api/support/bulletins?day=20261399")[0] == 400, "not a real date"
    assert s.call("GET", "/api/support/bulletins?day=20261122")[0] == 200
    assert s.call("POST", "/api/support/jobs/99999999999999999999/cancel")[0] == 404 and s.call("GET", "/api/support/jobs/99999999999999999999")[0] == 404
    assert add(s, name=[1, 2])[0] == 400 and add(s, name=True)[0] == 400 and add(s, name={"a": 1})[0] == 400, "a name that is not text"
    assert add(s, name=123)[0] == 422, "digits only: not a valid name, said so"
    st, body = add(s, name="221126_" + "A" * 5000); assert st == 422 and "too long" in str(body)
    assert add(s, name="221126_TAB\tAND\nNEWLINE")[0] in (200, 422), "control characters never crash"
    r = {"rundown": "34427", "story": "724921", "confirm": True, "clip_id": "5"}
    assert s.call("POST", "/api/support/remove", dict(r, clip_title=["x"]))[0] == 400 and s.call("POST", "/api/support/remove", dict(r, clip_title="T" * 600))[0] == 422
    assert s.call("POST", "/api/support/remove", dict(r, clip_title=7))[0] == 200, "a number is taken as its digits"
    assert s.svc("POST", "/svc/support/result", {"id": "abc", "state": "DONE"})[0] == 422 and s.svc("POST", "/svc/support/result", {"id": 10 ** 30, "state": "DONE"})[0] == 422


def test_requests_that_only_wait_never_use_up_the_places_of_the_ones_behind_them(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path)
    for i in range(10): assert add(s, name="221126_WAITING_%d" % i)[0] == 200                          # ten typed names whose files are not there yet
    jid = add(s, media_id="1103586")[1]["id"]; run(p)
    assert job(s, jid)["state"] == "DONE" and [x["mosObjectId"] for x in posts(f)] == ["1103586"], "the picked file is attached although ten requests are ahead of it"
    assert sum(1 for x in jobs(s) if x["state"] == "QUEUED") == 10, "and the waiting ones are still waiting"


def test_the_per_round_limit_still_stops_the_work_it_is_for(env, tmp_path, monkeypatch):
    from autoid_lite.blaze import support as sp
    s, f, p, e, did = ready_dry(tmp_path); jid = add(s, media_id="1103586")[1]["id"]
    monkeypatch.setattr(sp, "WORK_PER_ROUND", 0); run(p); assert job(s, jid)["state"] == "QUEUED" and not posts(f), "limit reached: left for the next round"
    monkeypatch.setattr(sp, "WORK_PER_ROUND", 8); run(p); assert job(s, jid)["state"] == "DONE" and len(posts(f)) == 1


def test_a_request_stuck_working_is_closed_by_the_page_as_unclear_and_never_resent(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); jid = add(s, media_id="1103586")[1]["id"]
    with s.app.db.tx() as cur: cur.x("UPDATE support_jobs SET state='WORKING', updated_at='2000-01-01T00:00:00Z' WHERE id=?", (jid,))
    st, body = s.svc("GET", "/svc/support/jobs?kind=ACTION"); assert st == 200 and [x["id"] for x in body if x.get("recovered")] == [jid], "the poller still gets it to settle by reading the story"
    with s.app.db.tx() as cur: assert cur.one("SELECT state FROM support_jobs WHERE id=?", (jid,))["state"] == "WORKING", "the poller's own question does not close it"
    a = s.call("GET", "/api/support/jobs")[1]; j = job(s, jid)
    assert j["state"] == "FAILED" and "unclear" in j["msg"] and a["open"] == 0 and not posts(f), "the page closes it: nothing stays open for ever, nothing is sent"
    with s.app.db.tx() as cur: assert cur.one("SELECT 1 FROM events WHERE action='support_failed'")
    run(p); assert not posts(f) and job(s, jid)["state"] == "FAILED"
    jid2 = add(s, media_id="1103586")[1]["id"]
    with s.app.db.tx() as cur: cur.x("UPDATE support_jobs SET state='WORKING' WHERE id=?", (jid2,))
    s.call("GET", "/api/support/jobs"); assert job(s, jid2)["state"] == "WORKING", "a request that has only just started is left alone"


def test_a_picked_file_is_not_carried_out_much_later_but_a_typed_name_waits_the_full_time(env, tmp_path):
    s, f, p, e, did = ready_dry(tmp_path); left = lambda j: calendar.timegm(time.strptime(j["expires_at"], "%Y-%m-%dT%H:%M:%SZ")) - time.time()
    a = add(s, media_id="1103586")[1]["id"]; b = add(s, name="221126_LATER_ONE")[1]["id"]
    assert 800 < left(job(s, a)) <= 901, "a picked file: 15 minutes"; assert 3500 < left(job(s, b)) <= 3601, "a typed name: SUPPORT_QUEUE_MINUTES (60)"
    with s.app.db.tx() as cur: cur.x("UPDATE support_jobs SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (a,))
    s.call("GET", "/api/support/jobs"); j = job(s, a); assert j["state"] == "EXPIRED" and "not attached in time" in j["msg"] and not posts(f)
    s.app.cfg["support_wait_min"] = 5; c = add(s, name="221126_FIVE_MIN")[1]["id"]; assert 200 < left(job(s, c)) <= 301
    s.call("POST", "/api/support/jobs/%d/cancel" % c); d = add(s, media_id="1103586")[1]["id"]; assert 200 < left(job(s, d)) <= 301, "never longer than the setting"


def test_a_bad_support_setting_falls_back_to_the_default_instead_of_stopping_the_program(env, monkeypatch):
    from autoid_lite.common import settings_from_env, support_minutes
    from autoid_lite.blaze.settings import Cfg
    assert [support_minutes(x) for x in ("abc", "", "  ", "0", "-5", "99999", "90", " 15 ", "1.5")] == [60, 60, 60, 1, 1, 1440, 90, 15, 60]
    assert [Cfg.support_list_secs_value(x) for x in ("fast", "", "0", "-3", "999", "nan", "inf", "3.5")] == [2.0, 2.0, 1.0, 1.0, 60.0, 2.0, 60.0, 3.5]
    monkeypatch.setenv("SUPPORT_LIST_SECS", "fast"); assert Cfg().support_list_secs == 2.0
    monkeypatch.setenv("SUPPORT_QUEUE_MINUTES", "abc"); assert settings_from_env()["support_wait_min"] == 60
