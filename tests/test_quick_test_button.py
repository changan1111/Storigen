"""v9.13: dashboard "Quick test attach". Per story, enabled only when the NITRO step is green; Yes / No; Yes sends ONE real attach of that clip even while BLAZE_ATTACH=dry."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_blaze_poll import bp, env, live_env, ready_clip, posts, watch_lines, clips

def dry(tmp_path, **extra):
    s, f, p, e = live_env(tmp_path, BLAZE_ATTACH="dry", BLAZE_LIVE_SHOW_IDS="", **extra); assert s.login()[0] == 200; return s, f, p, e
def cid(s, did):
    with s.app.db.tx() as cur: return cur.one("SELECT id FROM clip_ids WHERE display_id=?", (did,))["id"]
def row(s, did): return [x for x in clips(s) if x["display_id"] == did][0]
def ask(s, did, confirm=True): return s.call("POST", "/api/clips/%d/quickattach" % cid(s, did), {"confirm": True} if confirm else {})
def run(p, n=3):
    for _ in range(n): p.cycle()

def test_refused_until_nitro_is_green(env, tmp_path):
    from test_blaze_poll import slug
    s, f, p, e = dry(tmp_path); f.slugs = f.slugs + [slug(724921, "AUTO ID 05", 14, 20)]; p.cycle()
    did = [r for r in clips(s) if r["blaze_story_id"] == "724921"][0]["display_id"]      # story known, but Blaze's media list has no file yet
    st, body = ask(s, did); assert st == 409 and "NITRO is not green" in str(body) and row(s, did)["qa_state"] is None

def test_yes_attaches_exactly_that_clip_in_dry_mode(env, tmp_path):
    s, f, p, e = dry(tmp_path); a = ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 20, 1103586); b = ready_clip(s, f, p, 724922, "AUTO ID 06", 15, 20, 1103587)
    run(p); assert not posts(f), "dry: nothing is sent by itself"; assert row(s, a)["mos_object_id"] == "1103586"          # NITRO is green for both
    assert ask(s, a)[0] == 200 and row(s, a)["qa_state"] == "REQUESTED"
    run(p); assert [x["mosObjectId"] for x in posts(f)] == ["1103586"], "only the confirmed clip, one POST"
    assert row(s, a)["state"] == "ATTACHED" and row(s, a)["qa_state"] == "SENT" and row(s, b)["state"] != "ATTACHED" and row(s, b)["qa_state"] is None
    run(p); assert len(posts(f)) == 1, "never twice"
    assert any("QUICK TEST" in x and a in x for x in watch_lines(p))
    st, body = ask(s, a); assert st == 409 and "already attached" in str(body)
    assert [x for x in s.call("GET", "/api/clips")[1]["clips"] if x["display_id"] == a][0]["qa_state"] == "SENT"

def test_no_confirmation_no_request(env, tmp_path):
    s, f, p, e = dry(tmp_path); a = ready_clip(s, f, p); run(p, 1)
    assert ask(s, a, confirm=False)[0] == 400 and row(s, a)["qa_state"] is None; run(p); assert not posts(f)

def test_a_second_click_while_waiting_is_refused(env, tmp_path):
    s, f, p, e = dry(tmp_path); a = ready_clip(s, f, p); run(p, 1); assert ask(s, a)[0] == 200
    st, body = ask(s, a); assert st == 409 and "already waiting" in str(body)

def test_quicktest_scope_lines_do_not_stop_a_confirmed_button(env, tmp_path):
    s, f, p, e = dry(tmp_path, QUICKTEST_STORY_ID="999999"); a = ready_clip(s, f, p); run(p, 1); ask(s, a); run(p); assert len(posts(f)) == 1

def test_safety_rules_still_apply_kill_switch_and_unverified_format(env, tmp_path):
    (tmp_path / "k").mkdir(); s, f, p, e = dry(tmp_path / "k"); a = ready_clip(s, f, p); run(p, 1); (tmp_path / "k" / "STOP_LIVE").write_text("stop"); ask(s, a); run(p)
    assert not posts(f) and row(s, a)["qa_state"] == "BLOCKED" and "kill switch" in [x for x in s.call("GET", "/api/clips")[1]["clips"] if x["display_id"] == a][0]["qa_msg"]
    (tmp_path / "v").mkdir(); s, f, p, e = dry(tmp_path / "v"); a = ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 23); run(p, 1); ask(s, a); run(p)      # story format 23 (Package): itemId rule not verified
    assert not posts(f) and row(s, a)["qa_state"] == "BLOCKED" and row(s, a)["state"] != "ATTACHED"

def test_can_be_switched_off(env, tmp_path):
    s, f, p, e = dry(tmp_path); a = ready_clip(s, f, p); run(p, 1); s.app.cfg["quick_attach"] = False
    assert ask(s, a)[0] == 403 and s.call("GET", "/api/config")[1]["quick_attach"] is False

def test_dashboard_button_and_dialog_are_in_the_page():
    h = (pathlib.Path(__file__).resolve().parent.parent / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    for needle in ("Quick test attach", "/quickattach", "Yes, attach now", "c.stages.nitro", "qaWhyAll", "Yet to reach Nitro"): assert needle in h, needle
