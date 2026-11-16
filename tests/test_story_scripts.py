"""v9.13.2: the two script fields of every story (storyComplete -> versions[0].items[].text1 / text2) are read by the poller, kept in the registry and shown in two boxes on the story card and in the details."""
import sys, pathlib, sqlite3
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from test_blaze_poll import bp, env, live_env, ready_clip, posts, clips, slug
from test_shared_story_siblings import mk, shared_story
from autoid_lite import db as dbm
from autoid_lite.blaze.client import script_texts

ONLINE = "CHN - GAYATHRI\n\nகிண்டி, சென்னை\n\nவிசிக மீது திமுக வன்மத்தோடு செயல்படுகிறது - அமைச்சர் வன்னியரசு"
ANCHOR = "விடுதலை சிறுத்தைகள் கட்சியின் மீது திமுக வன்மத்தோடு செயல்படுவதாக அமைச்சர் வன்னியரசு குற்றம்சாட்டியுள்ளார். அந்த பேட்டியை தற்போது பார்க்கலாம்....."

def rows(s): return s.call("GET", "/api/clips")[1]["clips"]
def row(s, story): return [x for x in rows(s) if x["blaze_story_id"] == str(story)][0]
def spy(p):
    seen = []; real = p.a.call
    def call(path, payload=None): seen.append((path, payload)); return real(path, payload)
    p.a.call = call; return seen
def sent(seen): return [x for x in seen if x[0] == "/svc/scripts"]

def test_the_two_fields_reach_the_dashboard_and_the_details(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [slug(724921, "AUTO ID 05", 14), slug(724905, "AUTO ID 03", 13)]
    f.story_items["724921"] = [{"id": 900001, "arrangeOrder": 1, "text1": ONLINE, "text2": ANCHOR}]
    p.cycle(); a, b = row(s, 724921), row(s, 724905)
    assert a["online_script"] == ONLINE and a["anchor_script"] == ANCHOR and a["script_at"]
    assert b["online_script"] == "" and b["anchor_script"] == "" and b["script_at"]                 # read, and empty in Blaze: not "unread"
    full = s.call("GET", "/api/clips/%d/history" % a["id"])[1]["clip"]; assert full["online_script"] == ONLINE and full["anchor_script"] == ANCHOR
    assert s.call("GET", "/api/config")[1]["script_labels"] == ["Online script", "Anchor script"]

def test_the_card_list_carries_a_preview_only_and_the_details_the_full_text(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [slug(724921, "AUTO ID 05", 14)]; long = "x" * 3000
    f.story_items["724921"] = [{"id": 900001, "arrangeOrder": 1, "text1": long, "text2": long + "y"}]; p.cycle(); a = row(s, 724921)
    assert len(a["online_script"]) == 400 and a["online_len"] == 3000 and a["anchor_len"] == 3001          # a 700-story day stays light every 5 s
    assert len(s.call("GET", "/api/clips/%d/history" % a["id"])[1]["clip"]["anchor_script"]) == 3001

def test_stories_already_in_the_registry_are_filled_in_after_the_upgrade(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [slug(724921, "AUTO ID 05", 14), slug(724905, "AUTO ID 03", 13)]
    f.story_items["724921"] = [{"id": 900001, "arrangeOrder": 1, "text1": ONLINE, "text2": ANCHOR}]
    p.c.scripts = False; p.cycle()                                                                   # the stories exist in the registry, no script was ever read (what the upgrade finds)
    assert [x["script_at"] for x in rows(s)] == [None, None] and row(s, 724921)["online_script"] is None
    p.c.scripts = True; p.cycle(); assert row(s, 724921)["online_script"] == ONLINE and row(s, 724905)["script_at"]

def test_the_first_fill_runs_in_turns_and_new_stories_come_first(env):
    s, f, p = env; assert s.login()[0] == 200; p.c.script_batch = 5
    f.slugs = [slug(730000 + i, "S%d" % i, i + 1) for i in range(12)]
    for i in range(12): f.story_items[str(730000 + i)] = [{"id": 900001, "arrangeOrder": 1, "text1": "on %d" % i, "text2": "an %d" % i}]
    done = []
    for _ in range(3): p.cycle(); done.append(sum(1 for x in rows(s) if x["script_at"]))
    assert done == [5, 10, 12]                                                                        # never more than the batch per round
    f.slugs = f.slugs + [slug(731000, "NEW ONE", 99)]; f.story_items["731000"] = [{"id": 900001, "arrangeOrder": 1, "text1": "fresh", "text2": "fresh2"}]
    p.cycle(); assert row(s, 731000)["online_script"] == "fresh"                                      # a new story is read in the very next round

def test_an_edit_in_blaze_arrives_after_the_refresh_time_and_unchanged_text_is_not_sent_again(env):
    s, f, p = env; assert s.login()[0] == 200; f.slugs = [slug(724921, "AUTO ID 05", 14)]
    f.story_items["724921"] = [{"id": 900001, "arrangeOrder": 1, "text1": ONLINE, "text2": ANCHOR}]; seen = spy(p)
    p.cycle(); assert len(sent(seen)) == 1
    p.cycle(); assert len(sent(seen)) == 1                                                            # inside BLAZE_SCRIPT_SECS: not read again
    p.script_at["724921"] = 0; p.cycle(); assert len(sent(seen)) == 1                                 # read again, same text: nothing sent
    f.story_items["724921"] = [{"id": 900001, "arrangeOrder": 1, "text1": ONLINE, "text2": "NEW ANCHOR TEXT"}]
    p.script_at["724921"] = 0; p.cycle(); assert len(sent(seen)) == 2 and row(s, 724921)["anchor_script"] == "NEW ANCHOR TEXT" and row(s, 724921)["online_script"] == ONLINE

def test_several_items_are_joined_in_arrangeOrder_and_empty_ones_left_out():
    items = [{"id": 2, "arrangeOrder": 2, "text1": "second", "text2": None}, {"id": 1, "arrangeOrder": 1, "text1": " first ", "text2": "A1"}, {"id": 3, "arrangeOrder": 3, "text1": "   ", "text2": "A3"}]
    assert script_texts(items) == {"online": "first\n\nsecond", "anchor": "A1\n\nA3"}
    assert script_texts([]) == {"online": "", "anchor": ""} and script_texts([{"id": 1, "text1": 5, "text2": {}}]) == {"online": "", "anchor": ""}
    assert len(script_texts([{"id": 1, "text1": "z" * 50000}])["online"]) == 20000

def test_a_story_in_two_bulletins_gets_its_script_in_both(tmp_path, monkeypatch):
    s, f, p = mk(tmp_path, monkeypatch); assert s.login()[0] == 200
    f.story_items["731375"] = [{"id": 900001, "arrangeOrder": 1, "text1": ONLINE, "text2": ANCHOR}]
    rs, _ = shared_story(s, f, p); p.cycle()
    got = [x for x in rows(s) if x["blaze_story_id"] == "731375"]; assert len(got) == 2 and all(x["online_script"] == ONLINE and x["anchor_script"] == ANCHOR for x in got)

def test_the_service_endpoint_needs_the_key_a_list_and_caps_the_text(tmp_path):
    from test_server import Srv
    s = Srv(tmp_path, "story_id"); s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "1", "rundown_name": "A", "stories": [{"blaze_story_id": "555", "slug": "X", "slug_id": "9", "position": 1}]})
    assert s.call("POST", "/svc/scripts", {"stories": []}, key=False, cookie=False)[0] == 401
    assert s.svc("POST", "/svc/scripts", {"stories": "nope"})[0] == 422 and s.svc("POST", "/svc/scripts", {})[0] in (400, 422)
    st, r = s.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "555", "online": "o" * 30000, "anchor": 7}, {"blaze_story_id": "unknown", "online": "x"}, "junk", {"online": "no id"}]})
    assert st == 200 and r["updated"] == 1                                                            # the unknown story, the junk and the entry without an ID are skipped
    c = sqlite3.connect(str(tmp_path / "t.db")); c.row_factory = sqlite3.Row; x = c.execute("SELECT online_script, anchor_script FROM stories WHERE blaze_story_id='555'").fetchone()
    assert len(x["online_script"]) == 20000 and x["anchor_script"] == ""
    assert s.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "555", "online": "o" * 20000, "anchor": ""}]})[1]["updated"] == 0      # same text: nothing written

def test_nothing_is_written_to_blaze_and_a_script_problem_never_stops_the_round(env, monkeypatch):
    s, f, p = env; assert s.login()[0] == 200; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle()
    assert not [x for x in f.log if x[0] in ("PUT", "DELETE")] and not posts(f)
    monkeypatch.setattr(p, "read_scripts", lambda: 1 / 0); f.slugs = f.slugs + [slug(724905, "AUTO ID 03", 13)]
    p.cycle(); assert len(clips(s)) == 2                                                              # the new story was still synced

def test_the_script_reading_can_be_switched_off_and_tuned():
    c = bp.Cfg({"BLAZE_SHOW_IDS": "1"}); assert c.scripts and c.script_secs == 120 and c.script_batch == 40
    c = bp.Cfg({"BLAZE_SHOW_IDS": "1", "BLAZE_SCRIPTS": "0", "BLAZE_SCRIPT_SECS": "1", "BLAZE_SCRIPT_BATCH": "1"}); assert not c.scripts and c.script_secs == 15 and c.script_batch == 5

def test_labels_can_be_renamed(tmp_path):
    from test_server import Srv
    s = Srv(tmp_path, "story_id", {"SCRIPT_LABEL_ONLINE": "Online", "SCRIPT_LABEL_ANCHOR": "Anchor intro"}); assert s.login()[0] == 200
    assert s.call("GET", "/api/config")[1]["script_labels"] == ["Online", "Anchor intro"]

def test_the_database_upgrades_from_schema_6_and_keeps_its_data(tmp_path):
    p = tmp_path / "v6.db"; c = sqlite3.connect(str(p)); c.executescript(dbm.SCHEMA)
    for v, t, col, typ, _ in dbm.COLUMNS:
        if v <= 6 and col not in {x[1] for x in c.execute("PRAGMA table_info(%s)" % t)}: c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, col, typ))
    c.execute("INSERT INTO rundowns(id, blaze_rundown_id, name) VALUES(1,'R1','News')"); c.execute("INSERT INTO stories(id, blaze_story_id, rundown_id, slug) VALUES(1,'724921',1,'SLUG')")
    c.execute("PRAGMA user_version = 6"); c.commit(); c.close()
    d = dbm.DB(p); assert dbm.SCHEMA_VERSION >= 7 and d.conn.execute("PRAGMA user_version").fetchone()["user_version"] == dbm.SCHEMA_VERSION
    assert d.conn.execute("SELECT slug, online_script, anchor_script, script_at FROM stories").fetchone() == {"slug": "SLUG", "online_script": None, "anchor_script": None, "script_at": None}

def test_the_page_shows_two_boxes_next_to_the_quick_test_button_and_never_as_html():
    h = (pathlib.Path(__file__).resolve().parents[1] / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    fn = h[h.index("function scriptBoxes"):h.index("function card(")]
    assert "innerHTML" not in fn and "insertAdjacentHTML" not in fn                                     # script text goes through el(), which sets textContent: a script can never inject markup
    mid = h[h.index("function renderMid("):h.index("function kvr(")]; assert "innerHTML" not in mid      # v10.1.0: the script pane also goes through el() / textContent
    assert "r.append(scriptBoxes(c,false))" in h and "renderMid(c,same)" in h and "Quick test attach" in h and "quickAttach(c)" in h
