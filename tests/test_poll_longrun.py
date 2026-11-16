"""24/7 behaviour of the Blaze poller: fewer reads, cookie reload, alerts, flat memory, and the technical write boundary."""
import os as _os; _os.environ.setdefault("ID_FORMAT", "legacy")      # these tests pin the legacy YYYYMMDD_NNNNC_ ID; test_clip_names_and_versions.py covers DDMMYY_STORY_NAME
import pathlib, sys, time
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "tests"))
from test_blaze_poll import env, bp, slug, clips          # the fixture and helpers of the poller tests

def with_count(story, title, pos, n):
    sl = slug(story, title, pos); sl["storyId"]["clipCount"] = n; return sl
def complete_reads(f, story): return len([x for x in f.log if x[1].split("?")[0].endswith("/stories/%s/complete/" % story)])
def force_reconcile(p): p.last_rec = 0

# ---------------------------------------------------------------- fewer reads
def test_reconcile_reads_a_story_only_when_its_clip_count_changed(env):
    s, f, p = env; f.slugs = [with_count(1, "A", 1, 0)]; p.cycle(); r1 = complete_reads(f, 1); assert r1 >= 1       # first look reads it
    for _ in range(3): force_reconcile(p); p.cycle()
    assert complete_reads(f, 1) == r1, "unchanged clip count: no read"
    f.slugs[0]["storyId"]["clipCount"] = 1; force_reconcile(p); p.cycle()
    assert f.ident_calls.count("1") == 1 and complete_reads(f, 1) == r1, "the count moved: the cheap clip list is read once (layer B), the heavy /complete/ read is not repeated"
    force_reconcile(p); p.cycle(); assert f.ident_calls.count("1") == 1 and complete_reads(f, 1) == r1

def test_a_story_is_still_re_read_now_and_then_even_if_the_count_is_the_same(env):
    s, f, p = env; f.slugs = [with_count(1, "A", 1, 2)]; p.cycle(); r1 = complete_reads(f, 1)
    p.cc_read["1"] = (2, time.time() - p.c.full_recon - 1)             # last full read was too long ago: a swapped file keeps the same count
    force_reconcile(p); p.cycle(); assert complete_reads(f, 1) == r1 + 1

def test_without_a_clip_count_every_story_is_read_every_time_like_before(env):
    s, f, p = env; f.slugs = [slug(1, "A", 1)]; p.cycle(); r1 = complete_reads(f, 1)
    for _ in range(2): force_reconcile(p); p.cycle()
    assert complete_reads(f, 1) == r1 + 2

def test_a_failed_read_is_not_remembered_as_done(env):
    s, f, p = env; f.slugs = [with_count(1, "A", 1, 1)]; p.cycle(); f.expired = True; p.cc_read.clear()
    force_reconcile(p)
    with pytest.raises(bp.SessionExpired): p.reconcile()
    assert "1" not in p.cc_read

def test_memory_is_forgotten_for_stories_that_left_the_show(env):
    s, f, p = env; f.slugs = [with_count(1, "A", 1, 0), with_count(2, "B", 2, 0)]; p.cycle(); assert {"1", "2"} <= set(p.cc_read)
    f.slugs = [with_count(1, "A", 1, 0)]; force_reconcile(p); p.cycle()
    assert "2" not in p.cc_read and "2" not in p.pos and "2" not in p.fmt and "2" not in p.clipcount

# ---------------------------------------------------------------- session cookie reload + alerts
def test_session_cookie_is_reloaded_from_the_env_file(env, tmp_path, monkeypatch):
    s, f, p = env; ef = tmp_path / "autoid.env"; monkeypatch.setenv("AUTOID_ENV", str(ef))
    assert p.c.reload_session() is False                                # no file
    ef.write_text("BLAZE_SESSION_ID=NEWSID\nBLAZE_USERNAME=newuser\n"); assert p.c.reload_session() is True and (p.c.sid, p.c.user) == ("NEWSID", "newuser")
    assert p.c.reload_session() is False                                # unchanged
    ef.write_text("BLAZE_SESSION_ID=\n"); assert p.c.reload_session() is False and p.c.sid == "NEWSID"         # an empty value never wipes a working cookie
    ef.write_text("BLAZE_SESSION_ID=THIRD\n"); assert p.c.reload_session() is True and (p.c.sid, p.c.user) == ("THIRD", "newuser")

def test_session_problem_switches_to_a_new_cookie_or_alerts_once(env, tmp_path, monkeypatch):
    s, f, p = env; ef = tmp_path / "autoid.env"; monkeypatch.setenv("AUTOID_ENV", str(ef)); alerts = []; p.a.alert = alerts.append
    e = bp.SessionExpired("Blaze answered 401")
    bad = p.session_problem(e, False); assert bad is True and len(alerts) == 1 and "cookie" in alerts[0]          # nothing new in the file: alert once
    bad = p.session_problem(e, bad); assert bad is True and len(alerts) == 1                                      # and not again
    ef.write_text("BLAZE_SESSION_ID=FRESH\nBLAZE_USERNAME=u\n"); bad = p.session_problem(e, bad); assert bad is False and p.c.sid == "FRESH" and len(alerts) == 1

def test_the_new_cookie_is_the_one_sent_to_blaze(env, tmp_path, monkeypatch):
    s, f, p = env; seen = []
    import urllib.request as ur; real = ur.urlopen
    monkeypatch.setattr(bp.urllib.request, "urlopen", lambda req, timeout=None: (seen.append(req.get_header("Cookie")), real(req, timeout=timeout))[1])
    p.b.get("/DataService/shows/34427"); p.c.sid = "ROTATED"; p.b.get("/DataService/shows/34427")
    assert "sessionId=SID;" in seen[0] and "sessionId=ROTATED;" in seen[1]

def test_halting_live_attach_raises_an_alert(env, tmp_path):
    s, f, p = env; alerts = []; p.a.alert = alerts.append; p.c.stopfile = str(tmp_path / "STOP_LIVE")
    p.halt("3 live attaches in a row did not work")
    assert pathlib.Path(p.c.stopfile).exists() and len(alerts) == 1 and "HALTED" in alerts[0] and "3 live attaches" in alerts[0]

# ---------------------------------------------------------------- the technical write boundary
@pytest.mark.parametrize("method,path", [("PUT", "/DataService/stories/5"), ("POST", "/DataService/shows/1"), ("DELETE", "/DataService/shows/1"), ("DELETE", "/DataService/stories/5"),
                                         ("POST", "/DataService/stories/5/versions/1/lock"), ("PUT", "/DataService/stories/markStoryAsOnAir"), ("PUT", "/DataService/shows/1/slugs")])
def test_writes_other_than_keepalive_attach_and_undo_cannot_be_sent(env, method, path):
    s, f, p = env
    with pytest.raises(bp.ForbiddenCall): p.b.call(method, path)
    assert f.log == [], "nothing may reach Blaze"

def test_attach_cannot_be_sent_unless_live_and_the_keepalive_still_works(env):
    s, f, p = env; assert p.c.attach == "dry"
    with pytest.raises(bp.ForbiddenCall): p.b.attach("5", "34427", {"id": 1, "title": "t", "duration": 1000}, 1, "9")
    assert not [x for x in f.log if x[0] == "POST"]
    p.b.ping(); assert not [x for x in f.log if x[0] == "PUT"], "the default keep-alive is a GET, as the Blaze page does"
    p.c.heartbeat = "put"; p.b.ping(); assert [x for x in f.log if x[0] == "PUT" and x[1].startswith("/DataService/sessions/")], "the PUT keep-alive is still allowed when chosen"
    p.b.call("GET", "/DataService/shows/34427")                         # reads are never restricted
