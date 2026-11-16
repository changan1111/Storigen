"""v9.7.5: QUICKTEST_STORY_ID / QUICKTEST_SHOW_ID narrow real attaching to one story or one show; with nothing set, live means every show; dry never sends."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_blaze_poll import bp, env, live_env, ready_clip, posts, watch_lines

def two(s, f, p): ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 20, 1103586); ready_clip(s, f, p, 724922, "AUTO ID 06", 15, 20, 1103587)

def test_live_without_quicktest_attaches_every_story_with_no_hourly_cap(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_LIVE_SHOW_IDS=""); two(s, f, p); p.cycle(); p.cycle(); p.cycle()
    assert sorted(x["mosObjectId"] for x in posts(f)) == ["1103586", "1103587"]

def test_quicktest_story_attaches_only_that_story(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_LIVE_SHOW_IDS="", QUICKTEST_STORY_ID="724921"); two(s, f, p); p.cycle(); p.cycle(); p.cycle()
    assert [x["mosObjectId"] for x in posts(f)] == ["1103586"] and any("not QUICKTEST_STORY_ID" in x and "NOT SENT" in x for x in watch_lines(p))

def test_quicktest_show_attaches_only_that_show(env, tmp_path):
    for name, show, n in (("a", "99999", 0), ("b", "34427", 2)):
        d = tmp_path / name; d.mkdir(); s, f, p, e = live_env(d, BLAZE_LIVE_SHOW_IDS="", QUICKTEST_SHOW_ID=show); two(s, f, p); p.cycle(); p.cycle(); p.cycle(); assert len(posts(f)) == n

def test_dry_never_sends_even_with_quicktest_set(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_ATTACH="dry", QUICKTEST_STORY_ID="724921"); two(s, f, p); p.cycle(); p.cycle(); assert not posts(f)

def test_quicktest_command_reports_scope_and_story(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_LIVE_SHOW_IDS="", QUICKTEST_STORY_ID="724921"); did = ready_clip(s, f, p); p.cycle()
    t = bp.quicktest(p.c, ["724921"]); assert "only Blaze story 724921" in t and "INSIDE the scope" in t and did in t
    assert "outside the scope" in bp.quicktest(p.c, ["1"])
