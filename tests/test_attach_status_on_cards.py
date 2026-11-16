"""v9.13.1: every waiting clip's card says why it is not attached yet (the reason the poller already worked out, shown instead of only logged)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_blaze_poll import bp, env, live_env, ready_clip, posts, clips, slug

def row(s, did): return [x for x in s.call("GET", "/api/clips")[1]["clips"] if x["display_id"] == did][0]
def run(p, n=3):
    for _ in range(n): p.cycle()

def test_not_in_blaze_yet_and_dry_mode_have_their_own_words(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_ATTACH="dry", BLAZE_LIVE_SHOW_IDS=""); assert s.login()[0] == 200
    f.slugs = [slug(724930, "NO FILE YET", 3, 20)]; p.cycle(); did = clips(s)[0]["display_id"]
    assert "Not in Blaze's media list yet" in row(s, did)["why"]
    b = ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 20, 1103586); run(p)
    assert "Dry mode" in row(s, b)["why"] and "Quick test attach" in row(s, b)["why"] and not posts(f)

def test_a_blocked_clip_says_which_rule_blocked_it(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_LIVE_SHOW_IDS="", QUICKTEST_STORY_ID="999999"); assert s.login()[0] == 200
    a = ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 20, 1103586); run(p)
    w = row(s, a)["why"]; assert w.startswith("Blocked:") and "QUICKTEST_STORY_ID" in w and not posts(f)

def test_an_attached_clip_has_no_waiting_reason(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_LIVE_SHOW_IDS=""); assert s.login()[0] == 200
    a = ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 20, 1103586); run(p)
    assert row(s, a)["state"] == "ATTACHED" and row(s, a)["why"] is None

def test_a_clip_in_a_show_the_poller_does_not_follow_says_so(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_LIVE_SHOW_IDS=""); assert s.login()[0] == 200
    a = ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 20, 1103586); p.c.shows = ["99999"]; p.cycle()
    assert "does not follow show" in row(s, a)["why"]

def test_the_service_endpoint_checks_its_input(env):
    s, f, p = env; assert s.svc("POST", "/svc/why", {"why": "text"})[0] == 422 and s.svc("POST", "/svc/why", {"why": {"X": "y"}})[0] == 200
