"""v10.6.1: a Quick test on a clip the desk already attached by hand. The file is in the story, so the poller sends nothing; the clip is now marked ATTACHED and the answer says so
(it used to say 'Not sent'), and when the clip cannot be marked the card says why. Also: story format 22 (an unverified format) is blocked until it is named in BLAZE_VERIFIED_FORMATS."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_blaze_poll import bp, env, live_env, ready_clip, posts, watch_lines, clips
from test_quick_test_button import dry, ask, row, run

def card(s, did): return [x for x in s.call("GET", "/api/clips")[1]["clips"] if x["display_id"] == did][0]
def desk_attached(f, did, story="724921", mos=1103586): f.story_clips = {story: [(mos, did[:14] + "_SVO.mxf")]}

def test_desk_attached_first_then_quick_test_marks_it_attached_and_does_not_say_not_sent(env, tmp_path):
    s, f, p, e = dry(tmp_path); a = ready_clip(s, f, p); run(p, 2); assert row(s, a)["state"] != "ATTACHED"
    desk_attached(f, a); assert ask(s, a)[0] == 200; run(p, 2)
    c = card(s, a); assert c["state"] == "ATTACHED" and c["qa_state"] == "SENT", (c["state"], c["qa_state"], c["qa_msg"])
    assert "already in the story" in c["qa_msg"] and "nothing was sent by the tool" in c["qa_msg"] and not posts(f), "the desk had attached it: the tool sends nothing"
    assert any("QUICK TEST SENT" in x and a in x for x in watch_lines(p)) and not any("QUICK TEST BLOCKED" in x for x in watch_lines(p))

def test_when_the_clip_cannot_be_marked_the_answer_and_the_card_say_why(env, tmp_path):
    s, f, p, e = dry(tmp_path, BLAZE_CONFIRM="0"); a = ready_clip(s, f, p); run(p, 2); desk_attached(f, a); assert ask(s, a)[0] == 200; run(p, 2)
    c = card(s, a); assert c["state"] != "ATTACHED" and c["qa_state"] == "BLOCKED" and not posts(f)
    assert "already in the story" in c["qa_msg"] and "not marked ATTACHED yet" in c["qa_msg"] and "BLAZE_CONFIRM=0" in c["qa_msg"], c["qa_msg"]
    assert "BLAZE_CONFIRM=0" in p.why_map[a] and "not marked ATTACHED yet" in p.why_map[a], "the 'why waiting' text on the card names the reason too"

def test_the_identity_reading_alone_is_enough_to_confirm():
    m = {"id": 1103586}; info = {"clips": [("5", "other.mxf")], "rows": [{"id": "9", "mos": "5", "title": "other.mxf", "dur": 1, "item": None}], "shows": ["34427"]}
    idn = ([{"id": "77", "mos": "1103586", "title": "171126_X_SVO.mxf", "dur": 50000}], 123.0, None)
    got = bp.Poller.with_ident(info, idn, m)
    assert [x for x, _ in got["clips"]].count("1103586") == 1 and got["shows"] == ["34427"] and any(r["mos"] == "1103586" and r["id"] == "77" for r in got["rows"])
    assert info["clips"] == [("5", "other.mxf")], "the cached details are copied, never changed"
    assert bp.Poller.with_ident(got, idn, m) is got, "already listed: unchanged"
    assert bp.Poller.with_ident(info, None, m) is info and bp.Poller.with_ident(info, ([], 1.0, None), m) is info
    twice = ([{"id": "1", "mos": "1103586", "title": "a", "dur": 1}, {"id": "2", "mos": "1103586", "title": "a", "dur": 1}], 1.0, None)
    assert bp.Poller.with_ident(info, twice, m) is info, "twice in the story is a duplicate: nothing is added, so nothing is marked"

def test_story_format_22_is_blocked_until_it_is_a_verified_format(env, tmp_path):
    (tmp_path / "a").mkdir(); s, f, p, e = dry(tmp_path / "a"); a = ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 22); run(p, 1); assert ask(s, a)[0] == 200; run(p, 2)
    c = card(s, a); assert c["qa_state"] == "BLOCKED" and c["state"] != "ATTACHED" and not posts(f)
    assert "story format 22" in c["qa_msg"] and "BLAZE_VERIFIED_FORMATS" in c["qa_msg"], c["qa_msg"]
    (tmp_path / "b").mkdir(); s, f, p, e = dry(tmp_path / "b", BLAZE_VERIFIED_FORMATS="20,21,22"); a = ready_clip(s, f, p, 724921, "AUTO ID 05", 14, 22); run(p, 1); assert ask(s, a)[0] == 200; run(p, 2)
    c = card(s, a); assert c["state"] == "ATTACHED" and c["qa_state"] == "SENT" and len(posts(f)) == 1, (c["state"], c["qa_state"], c["qa_msg"])
