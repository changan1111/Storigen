"""v10.4.0: an attach that ended unclear (read-back failed, session expired, restart while SENDING). Blaze may take longer than expected to show the clip:
the poller keeps reading the story and marks every clip ID when the exact file appears; the original POST is NEVER sent again; the clock runs from the FIRST send and survives restarts;
only one unsettled attempt per story, atomically, across clip IDs, Quick test and processes; the settling check is the exact media object id."""
import sys, pathlib, subprocess, threading, time
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_blaze_poll import posts, clips, watch_lines, bp
from test_shared_story_edge_cases import build, wrap, states, STORY
import blaze_ledger as bl

def fname(rows): return rows[0]["name_id"].replace("_", " ") + ".mxf"
def age(p, secs): p.led.c.execute("UPDATE live SET sent_at=sent_at-?", (secs,))
def unclear(tmp_path, monkeypatch):
    """The POST went out (Blaze accepted it, shows nothing yet) and the read-back timed out."""
    s, f, p, rows = build(tmp_path, monkeypatch); f.post_mode = "noop"; st = {"done": False}
    def fn(orig, sid):
        if posts(f) and not st["done"]: st["done"] = True; raise TimeoutError("read timed out")
        return orig(sid)
    wrap(p, fn); p.cycle(); assert len(posts(f)) == 1
    did = [x for x in p.led.live_rows(5)][0]["display_id"]; assert p.led.live_of(did)["status"] == "UNKNOWN"
    return s, f, p, rows, did

def test_1040_40_late_exposure_is_picked_up_and_the_post_is_never_repeated(tmp_path, monkeypatch):
    s, f, p, rows, did = unclear(tmp_path, monkeypatch)
    for _ in range(3): p.last_rec = 0; p.cycle()                                 # Blaze still shows nothing
    assert len(posts(f)) == 1 and states(s) == ["ON_NITRO"] * 3
    f.story_clips = {STORY: [(1113224, fname(rows))]}                           # Blaze catches up
    for _ in range(3): p.last_rec = 0; p.cycle()
    assert len(posts(f)) == 1 and states(s) == ["ATTACHED"] * 3

def test_1040_41_after_the_wait_the_desk_is_told_but_a_late_clip_still_marks_everything(tmp_path, monkeypatch):
    s, f, p, rows, did = unclear(tmp_path, monkeypatch); age(p, 400); p.last_rec = 0; p.cycle()
    assert states(s) == ["NEEDS_DESK"] * 3                                        # the registry keeps one state per file: the desk sees every bulletin's clip ID
    assert any("ended unclear" in x and "may still arrive" in x for x in watch_lines(p)) and len(posts(f)) == 1
    f.story_clips = {STORY: [(1113224, fname(rows))]}
    for _ in range(3): p.last_rec = 0; p.cycle()
    assert states(s) == ["ATTACHED"] * 3 and len(posts(f)) == 1

def test_1040_42_the_clock_counts_from_the_first_send_and_survives_a_restart(tmp_path, monkeypatch):
    s, f, p, rows, did = unclear(tmp_path, monkeypatch); first = p.led.live_of(did)["sent_at"]
    age(p, 200); first -= 200; p2 = bp.Poller(bp.Cfg(p.e)); p2.show_meta = p.show_meta; wrap(p2, lambda orig, sid: orig(sid))      # the service restarted
    p2.cycle(); p2.cycle(); assert p2.led.live_of(did)["sent_at"] == first, "a restart or another read never moves the first-send time"
    assert not posts(f) or len(posts(f)) == 1; assert [r["state"] for r in clips(s) if r["display_id"] == did] == ["ON_NITRO"], "200 s is inside the 300 s wait"
    age(p2, 150); p2.cycle(); assert [r["state"] for r in clips(s) if r["display_id"] == did] == ["NEEDS_DESK"] and len(posts(f)) == 1

def test_1040_43_the_wait_cannot_be_set_below_two_minutes():
    assert bp.Cfg({"BLAZE_SHOW_IDS": "1", "BLAZE_UNCLEAR_SECS": "5"}).unclear_secs == 120 and bp.Cfg({"BLAZE_SHOW_IDS": "1"}).unclear_secs == 300

def test_1040_44_the_claim_is_one_atomic_step_per_story(tmp_path):
    a, b = bl.Ledger(tmp_path / "l.db"), bl.Ledger(tmp_path / "l.db")                      # two connections to one file: two processes, or the poller and a Quick test
    assert a.live_start("A", "S1", "1", 10, "a.mxf") and not b.live_start("B", "S1", "2", 10, "a.mxf"), "same story, same file: one wins"
    assert not b.live_start("C", "S1", "2", 11, "c.mxf"), "same story, another file: still waits while the first is unsettled"
    assert b.live_start("D", "S2", "1", 10, "a.mxf"), "another story is never blocked"
    a.live_finish("A", "UNKNOWN"); assert not b.live_start("E", "S1", "2", 10, "a.mxf")
    a.live_finish("A", "SENT"); assert not b.live_start("E2", "S1", "2", 10, "a.mxf"), "a sibling can never send a file the story already got from us"
    assert b.live_start("F", "S1", "2", 11, "c.mxf"), "a settled attempt no longer blocks another file"
    a.live_finish("F", "FAILED"); assert b.live_start("G", "S1", "3", 12, "g.mxf") and not b.live_start("H", "S1", "3", 11, "c.mxf"), "a refused attempt blocks only the same file"

def test_1040_45_many_threads_and_many_processes_cannot_both_claim(tmp_path):
    path = tmp_path / "l.db"; bl.Ledger(path); wins = []; lock = threading.Lock()
    def go(i):
        led = bl.Ledger(path); ok = led.live_start("T%d" % i, "SX", "1", 10, "a.mxf")
        with lock: wins.append(ok)
    th = [threading.Thread(target=go, args=(i,)) for i in range(16)]; [t.start() for t in th]; [t.join() for t in th]
    assert wins.count(True) == 1 and len(wins) == 16
    code = ("import sys,time; sys.path.insert(0,%r); import blaze_ledger as bl; led=bl.Ledger(%r); t=float(sys.argv[2]); time.sleep(max(0,t-time.time())); print(led.live_start('P'+sys.argv[1],'SY','1',10,'a.mxf'))"
            % (str(pathlib.Path(__file__).resolve().parent.parent / "tools"), str(path)))
    t0 = time.time() + 1.5; procs = [subprocess.Popen([sys.executable, "-c", code, str(i), str(t0)], stdout=subprocess.PIPE, text=True) for i in range(8)]
    outs = [p.communicate()[0].strip() for p in procs]; assert outs.count("True") == 1 and outs.count("False") == 7, outs

def test_1040_46_two_pollers_racing_on_one_shared_story_send_once(tmp_path, monkeypatch):
    for round_ in range(3):                                                       # the interleaving differs from run to run
        s, f, p, rows = build(tmp_path / ("r%d" % round_), monkeypatch) if (tmp_path / ("r%d" % round_)).mkdir() is None else None
        errs = []; go = threading.Event()
        def other():                                                              # a second poller process-alike: its own ledger connection, created in its own thread
            try:
                q = bp.Poller(bp.Cfg(p.e)); q.show_meta = p.show_meta; go.wait(); q.cycle()
            except BaseException as e: errs.append(e)
        t = threading.Thread(target=other); t.start(); go.set(); p.cycle(); t.join()
        assert not errs, errs
        assert len(posts(f)) == 1, "one POST however the two pollers interleave (round %d)" % round_

def test_1040_47_only_the_exact_media_object_settles_an_attempt(tmp_path, monkeypatch):
    s, f, p, rows, did = unclear(tmp_path, monkeypatch)
    f.story_clips = {STORY: [(999, fname(rows))]}                                   # some OTHER media object with the same title is in the story
    for _ in range(3): p.last_rec = 0; p.cycle()
    assert p.led.live_of(did)["status"] == "UNKNOWN", "not settled by a clip that is merely in the story"
    assert len(posts(f)) == 1, "and the file is not sent again"
    f.story_clips = {STORY: [(999, fname(rows)), (1113224, fname(rows))]}           # the exact object appears
    p.last_rec = 0; p.cycle()
    # the settle happens when a later attach of this story looks at it; the file itself is now in the story, so nothing more is ever sent
    assert len(posts(f)) == 1
