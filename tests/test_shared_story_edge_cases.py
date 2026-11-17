"""v10.4.0 edge cases of the shared-story attach: unverifiable membership, read-back failures, a bulletin that loses the story, concurrent desk attach,
Quick test on a sibling, six bulletins with different rows, two Quick tests at once, an expired session right after the POST, a restart while SENDING."""
import sys, pathlib, time, datetime as dt
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_blaze_poll import Fake, slug, media, clips, posts, bp, LIVE, set_state, watch_lines, live_env
from test_quick_test_button import ask, row, run
from test_shared_story_attach import iso
from autoid_lite.blaze.errors import SessionExpired

IDS = ["34427", "34428", "34429", "34430", "34431", "34432"]
STORY = "731375"

def build(tmp_path, monkeypatch, n=3, pos=None, mode="live", **extra):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1")
    ids = IDS[:n]; cfg = {"BLAZE_SHOW_IDS": ",".join(ids), **extra}
    if mode == "live": cfg["BLAZE_LIVE_SHOW_IDS"] = ",".join(ids)
    else: cfg.update(BLAZE_ATTACH="dry", BLAZE_LIVE_SHOW_IDS="")
    s, f, p, e = live_env(tmp_path, **cfg); assert s.login()[0] == 200
    f.linked = {STORY: [int(x) for x in ids[1:]]}; pos = pos or [49 - 5 * i for i in range(n)]
    a = slug(int(STORY), "HL ONLY SLM - SCHOOL ISSUE 1 PM", pos[0], 20)
    f.slugs_by_show = {sh: [dict(a, id=a["id"] + 100 * i, finalPosition=pos[i])] for i, sh in enumerate(ids)}; p.cycle()
    rows = sorted(clips(s), key=lambda r: ids.index(r["blaze_rundown_id"])); assert len(rows) == n and len({r["name_id"] for r in rows}) == 1
    for r in rows: set_state(s, r["display_id"], "ON_NITRO")
    f.medias = [media(1113224, rows[0]["name_id"].replace("_", " ") + ".mxf")]
    p.show_meta = {sh: {"start": iso(-20 if i == 0 else 60 * i)} for i, sh in enumerate(ids)}      # the first bulletin is on air, the others come later
    p.e = e; return s, f, p, rows

def states(s): return sorted(r["state"] for r in clips(s))
def wrap(p, fn): orig = p.b.story_info; p.b.story_info = lambda sid, _o=orig: fn(_o, sid)

def test_1040_20_an_empty_show_list_marks_no_sibling(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch, mode="dry"); info = p.b.story_info(STORY); m = {"id": 1113224, "title": "x.mxf", "duration": 50000}
    p.rows = [dict(r) for r in clips(s)]; r0 = p.rows[0]; info["clips"] = [("1113224", "x")]
    assert p.confirm_group(r0, STORY, dict(info, shows=[]), m, "blaze_readback")
    assert [x["state"] for x in p.rows].count("ATTACHED") == 1 and r0["state"] == "ATTACHED", "only the clip ID being handled, never the siblings"
    assert any("gave no show list" in x for x in watch_lines(p))

def test_1040_21_a_missing_show_field_is_not_verified_membership(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch, mode="dry"); info = dict(p.b.story_info(STORY)); info.pop("shows"); info["clips"] = [("1113224", "x")]
    p.rows = [dict(r) for r in clips(s)]; p.confirm_group(p.rows[0], STORY, info, {"id": 1113224, "title": "x.mxf", "duration": 50000}, "blaze_readback")
    assert [x["state"] for x in p.rows].count("ATTACHED") == 1

def test_1040_22_post_succeeds_but_the_read_back_times_out(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch); st = {"done": False}
    def fn(orig, sid):
        if posts(f) and not st["done"]: st["done"] = True; raise TimeoutError("read timed out")           # the first read after the POST
        return orig(sid)
    wrap(p, fn); p.cycle()
    assert len(posts(f)) == 1 and any("READ-BACK FAILED" in x for x in watch_lines(p))
    for _ in range(4): p.last_rec = 0; p.cycle()
    assert len(posts(f)) == 1, "never sent again"
    assert states(s) == ["ATTACHED"] * 3, "the next read of the story marks every clip ID"

def test_1040_23_the_chosen_bulletin_loses_the_story_before_the_post(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch)
    wrap(p, lambda orig, sid: dict(orig(sid), shows=[x for x in orig(sid)["shows"] if x != "34427"]))          # planning chose 34427 (on air); Blaze no longer lists it
    p.cycle(); assert not posts(f) and states(s) == ["ON_NITRO"] * 3

def test_1040_24_the_desk_attaches_the_same_file_while_the_tool_is_about_to(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch); n = rows[0]["name_id"].replace("_", " ") + ".mxf"; seen = {"c": 0}
    def fn(orig, sid):
        seen["c"] += 1
        if seen["c"] == 2: f.story_clips = {STORY: [(1113224, n)]}                  # between the planning read and the last look before sending
        return orig(sid)
    wrap(p, fn); p.cycle(); assert not posts(f), "the last look sees the desk's clip"
    for _ in range(3): p.last_rec = 0; p.cycle()
    assert states(s) == ["ATTACHED"] * 3 and len(f.story_clips[STORY]) == 1

def test_1040_25_quick_test_on_one_sibling_of_three_rundowns(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch, n=3, mode="dry"); run(p); assert not posts(f)
    mid = rows[1]["display_id"]; assert ask(s, mid)[0] == 200; run(p)
    assert len(posts(f)) == 1 and states(s) == ["ATTACHED"] * 3
    assert row(s, mid)["qa_state"] == "SENT" and all(row(s, r["display_id"])["qa_state"] in (None, "SENT") for r in rows)

def test_1040_26_six_rundowns_with_different_rows(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch, n=6, pos=[10, 20, 30, 40, 50, 60])
    p.show_meta = {sh: {"start": iso(-300 + 100 * i)} for i, sh in enumerate(IDS)}; p.show_meta["34430"] = {"start": iso(-15)}      # 34430 is on air (row 40)
    p.cycle(); form = posts(f)[0]; assert len(posts(f)) == 1 and form["showId"] == "34430" and form["order"] == "41"
    assert states(s) == ["ATTACHED"] * 6

def test_1040_27_two_quick_tests_almost_at_once(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch, n=3, mode="dry"); run(p)
    assert ask(s, rows[0]["display_id"])[0] == 200 and ask(s, rows[2]["display_id"])[0] == 200; run(p)
    assert len(posts(f)) == 1 and states(s) == ["ATTACHED"] * 3 and len(f.story_clips[STORY]) == 1
    assert row(s, rows[0]["display_id"])["qa_state"] == "SENT" and row(s, rows[2]["display_id"])["qa_state"] == "SENT"

def test_1040_28_the_session_expires_right_after_the_post(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch); st = {"raised": False}
    def fn(orig, sid):
        if posts(f) and not st["raised"]: st["raised"] = True; raise SessionExpired("session gone")
        return orig(sid)
    wrap(p, fn)
    try: p.cycle()
    except BaseException as e: pass
    for _ in range(4):
        try: p.last_rec = 0; p.cycle()
        except BaseException: pass
    assert len(posts(f)) == 1, "an attach that was sent is never repeated"
    assert states(s) == ["ATTACHED"] * 3

def test_1040_29_restart_while_an_attach_was_sending(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch); r = rows[0]
    assert p.led.live_start(r["display_id"], STORY, "34427", 1113224, "x.mxf")                   # the service died after writing this record
    p.cycle(); assert not posts(f) and all(x["state"] == "ON_NITRO" for x in clips(s)), "never sent a second time"
    p.led.c.execute("UPDATE live SET sent_at=sent_at-1000"); p.cycle(); assert not posts(f)
    assert [x for x in clips(s) if x["display_id"] == r["display_id"]][0]["state"] == "NEEDS_DESK" and any("ended unclear" in x for x in watch_lines(p))

def test_1040_30_restart_while_sending_but_the_attach_had_arrived(tmp_path, monkeypatch):
    s, f, p, rows = build(tmp_path, monkeypatch); n = rows[0]["name_id"].replace("_", " ") + ".mxf"
    assert p.led.live_start(rows[0]["display_id"], STORY, "34427", 1113224, n); f.story_clips = {STORY: [(1113224, n)]}
    for _ in range(3): p.last_rec = 0; p.cycle()
    assert not posts(f) and states(s) == ["ATTACHED"] * 3
