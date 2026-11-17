"""v10.4.0: a story that sits in several bulletins (several showIds) is attached ONCE, in the current bulletin (else the next future one, else the latest that aired);
Blaze then shows the clip in every bulletin of the story, so every clip ID of that story is read back and marked ATTACHED. Field case: 161126_DIST_CHN_MARINA_HORSE_ISSUE_HL,
story 734249 in six bulletins, was BLOCKED by 'CHECK: story is linked in shows ...', and after the desk attached it by hand the read-back crashed with KeyError 'rows'."""
import sys, pathlib, datetime as dt
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_blaze_poll import Fake, slug, media, clips, posts, bp, LIVE, set_state, watch_lines, live_env

SHOWS = {"BLAZE_SHOW_IDS": "34427,34428", "BLAZE_LIVE_SHOW_IDS": "34427,34428"}
iso = lambda mins: (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=mins)).isoformat(timespec="seconds")

def shared(tmp_path, monkeypatch, pos=(49, 7), **extra):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1")
    s, f, p, e = live_env(tmp_path, **{**SHOWS, **extra}); f.linked = {"731375": [34428]}
    a = slug(731375, "HL ONLY SLM - SCHOOL ISSUE 1 PM", pos[0], 20); b = dict(slug(731375, "HL ONLY SLM - SCHOOL ISSUE 1 PM", pos[1], 20), id=a["id"] + 500)
    f.slugs_by_show = {"34427": [a], "34428": [b]}; p.cycle(); rows = clips(s)
    assert len(rows) == 2 and len({r["name_id"] for r in rows}) == 1
    return s, f, p, rows

def ready(s, f, p, rows):
    for r in rows: set_state(s, r["display_id"], "ON_NITRO")
    f.medias = [media(1113224, rows[0]["name_id"].replace("_", " ") + ".mxf")]

def test_1040_01_one_attach_marks_every_clip_id_of_the_shared_story(tmp_path, monkeypatch):
    s, f, p, rows = shared(tmp_path, monkeypatch); ready(s, f, p, rows)
    p.show_meta = {"34427": {"start": iso(-20)}, "34428": {"start": iso(90)}}; p.cycle()
    assert len(posts(f)) == 1, "ONE attach, not one per bulletin"
    assert sorted(r["state"] for r in clips(s)) == ["ATTACHED", "ATTACHED"]
    assert not any("NOT SENT" in x and "linked in shows" in x for x in watch_lines(p)) and not any("confirm failed" in x for x in watch_lines(p))
    p.cycle(); p.cycle(); assert len(posts(f)) == 1

def test_1040_02_the_attach_goes_through_the_current_bulletin_with_its_own_row(tmp_path, monkeypatch):
    s, f, p, rows = shared(tmp_path, monkeypatch); ready(s, f, p, rows)
    p.show_meta = {"34427": {"start": iso(-200)}, "34428": {"start": iso(-10)}}; p.cycle()         # 34428 is on air now
    form = posts(f)[0]; assert form["showId"] == "34428" and form["order"] == "8"                     # its own row (7), not the other bulletin's (49)

def test_1040_03_carrier_current_then_next_then_latest_aired(tmp_path, monkeypatch):
    s, f, p, rows = shared(tmp_path, monkeypatch)
    p.show_meta = {"34427": {"start": iso(-300)}, "34428": {"start": iso(-30)}}; assert p.carrier("731375", "34427") == ("34428", "the current bulletin")
    p.show_meta = {"34427": {"start": iso(-300)}, "34428": {"start": iso(120)}}; assert p.carrier("731375", "34427") == ("34428", "the next bulletin")
    p.show_meta = {"34427": {"start": iso(-300)}, "34428": {"start": iso(-120)}}; assert p.carrier("731375", "34427") == ("34428", "the latest bulletin (all have aired)")
    p.show_meta = {}; assert p.carrier("731375", "34427")[0] == "34427"                                 # no start times known: the row's own bulletin

def test_1040_04_already_aired_bulletins_are_attached_too(tmp_path, monkeypatch):
    s, f, p, rows = shared(tmp_path, monkeypatch); ready(s, f, p, rows)
    p.show_meta = {"34427": {"start": iso(-600)}, "34428": {"start": iso(-300)}}; p.cycle()
    assert len(posts(f)) == 1 and sorted(r["state"] for r in clips(s)) == ["ATTACHED", "ATTACHED"]

def test_1040_05_a_bulletin_blaze_does_not_list_for_the_story_is_not_marked(tmp_path, monkeypatch):
    s, f, p, rows = shared(tmp_path, monkeypatch); ready(s, f, p, rows); f.linked = {}                 # Blaze's read-back lists only 34427 for the story
    p.show_meta = {"34427": {"start": iso(-20)}, "34428": {"start": iso(90)}}; p.cycle()
    by = {r["blaze_rundown_id"]: r["state"] for r in clips(s)}; assert by["34427"] == "ATTACHED" and by["34428"] != "ATTACHED"
    assert any("SHARED NOT SEEN" in x for x in watch_lines(p))

def test_1040_06_dry_run_describes_the_shared_attach_and_sends_nothing(tmp_path, monkeypatch):
    s, f, p, rows = shared(tmp_path, monkeypatch, BLAZE_ATTACH="dry"); ready(s, f, p, rows)
    p.show_meta = {"34427": {"start": iso(-20)}, "34428": {"start": iso(90)}}; p.cycle()
    L = [x for x in watch_lines(p) if "GOING TO ATTACH" in x]; assert L and all("SHARED story" in x and "ONE attach in show 34427" in x and "DRY RUN" in x and "NOT SENT" not in x for x in L)
    assert not posts(f)

def test_1040_07_file_already_in_the_shared_story_marks_all_clip_ids(tmp_path, monkeypatch):
    s, f, p, rows = shared(tmp_path, monkeypatch, BLAZE_ATTACH="dry"); ready(s, f, p, rows)
    f.story_clips = {"731375": [(1113224, rows[0]["name_id"].replace("_", " ") + ".mxf")]}; p.cycle()
    assert sorted(r["state"] for r in clips(s)) == ["ATTACHED", "ATTACHED"]

def test_1040_08_a_file_twice_in_the_story_is_not_marked(tmp_path, monkeypatch):
    s, f, p, rows = shared(tmp_path, monkeypatch, BLAZE_ATTACH="dry"); ready(s, f, p, rows); n = rows[0]["name_id"].replace("_", " ") + ".mxf"
    f.story_clips = {"731375": [(1113224, n), (1113224, n)]}; p.cycle(); assert all(r["state"] != "ATTACHED" for r in clips(s))

def test_1040_09_desk_attach_read_back_marks_every_clip_id_without_a_crash(tmp_path, monkeypatch):
    """The desk attached by hand: the changed attachment count makes the poller read the story at once (the fresh identity read), which crashed with KeyError 'rows'."""
    s, f, p, rows = shared(tmp_path, monkeypatch, BLAZE_ATTACH="dry"); ready(s, f, p, rows); p.cycle()
    n = rows[0]["name_id"].replace("_", " ") + ".mxf"; f.story_clips = {"731375": [(1113224, n)]}
    for sh in f.slugs_by_show:
        for sl in f.slugs_by_show[sh]: sl["storyId"].update({"clipCount": 1, "clipDur": 50, "clipStatus": "READY"})
    p.cycle(); p.cycle()
    assert sorted(r["state"] for r in clips(s)) == ["ATTACHED", "ATTACHED"]

def test_1040_10_only_the_newest_version_is_attached_to_the_shared_story(tmp_path, monkeypatch):
    s, f, p, rows = shared(tmp_path, monkeypatch, BLAZE_VERSION_MODE="auto"); ready(s, f, p, rows)
    base = rows[0]["name_id"]; v2 = base + "_V2"
    with s.app.db.tx() as cur: cur.x("UPDATE clip_ids SET version=2, name_id=? WHERE display_id=?", (v2, rows[1]["display_id"]))
    f.medias = [media(1113224, base.replace("_", " ") + ".mxf"), media(1113999, v2.replace("_", " ") + ".mxf")]
    p.show_meta = {"34427": {"start": iso(-20)}, "34428": {"start": iso(90)}}; p.cycle()
    assert [x["mosObjectId"] for x in posts(f)] == ["1113999"], "the older version is not attached again: the latest version is used everywhere"
