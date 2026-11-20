"""v10.9.7: every Online (text1) and Anchor (text2) text of a story is kept item by item, so the middle pane shows each one in its own box,
with a word count and a reading time (words per minute typed at the top), also for the part of a text the editor selects."""
import sys, pathlib, sqlite3, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from test_blaze_poll import env, slug
from test_story_scripts import row, rows
from autoid_lite import db as dbm
from autoid_lite.blaze.client import script_items, script_texts

ROOT = pathlib.Path(__file__).resolve().parents[1]
def page(): return (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")

ITEMS = [{"id": 2, "arrangeOrder": 2, "text1": "second online", "text2": None}, {"id": 1, "arrangeOrder": 1, "text1": " first online ", "text2": "A1"},
         {"id": 3, "arrangeOrder": 3, "text1": "   ", "text2": "A3"}, {"id": 4, "arrangeOrder": 4, "text1": "", "text2": ""}]

def test_items_keep_their_own_number_and_empty_ones_are_left_out():
    assert script_items(ITEMS) == [{"n": 1, "online": "first online", "anchor": "A1"}, {"n": 2, "online": "second online", "anchor": ""}, {"n": 3, "online": "", "anchor": "A3"}]
    assert script_items([]) == [] and script_items([{"id": 1, "text1": 5, "text2": {}}]) == []
    assert len(script_items([{"id": 1, "text1": "z" * 50000}])[0]["online"]) == 20000
    assert script_texts(ITEMS) == {"online": "first online\n\nsecond online", "anchor": "A1\n\nA3"}      # the joined text is unchanged

def test_the_items_reach_the_dashboard_and_follow_an_edit(env):
    s, f, p = env; assert s.login()[0] == 200; f.slugs = [slug(724921, "AUTO ID 05", 14)]; f.story_items["724921"] = ITEMS; p.cycle()
    a = row(s, 724921); full = s.call("GET", "/api/clips/%d/history" % a["id"])[1]["clip"]
    assert full["script_items"] == script_items(ITEMS) and full["online_script"] == "first online\n\nsecond online"
    f.story_items["724921"] = [dict(ITEMS[1], text1="first online EDITED")] + ITEMS[:1] + ITEMS[2:]; p.script_at["724921"] = 0; p.cycle()
    assert s.call("GET", "/api/clips/%d/history" % a["id"])[1]["clip"]["script_items"][0]["online"] == "first online EDITED"
    f.story_items["724921"] = [dict(ITEMS[0], arrangeOrder=1)]; p.script_at["724921"] = 0; p.cycle()                       # text1 of one item only
    assert s.call("GET", "/api/clips/%d/history" % a["id"])[1]["clip"]["script_items"] == [{"n": 1, "online": "second online", "anchor": ""}]

def test_the_service_endpoint_checks_and_caps_the_items(tmp_path):
    from test_server import Srv
    s = Srv(tmp_path, "story_id"); s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "1", "rundown_name": "A", "stories": [{"blaze_story_id": "555", "slug": "X", "slug_id": "9", "position": 1}]})
    junk = [{"n": 1, "online": "o" * 30000, "anchor": 7}, "junk", {"n": "x", "online": "two", "anchor": "A"}, {"online": "", "anchor": ""}]
    st, r = s.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "555", "online": "o", "anchor": "a", "items": junk}]}); assert st == 200 and r["updated"] == 1
    c = sqlite3.connect(str(tmp_path / "t.db")); c.row_factory = sqlite3.Row; it = json.loads(c.execute("SELECT script_items FROM stories WHERE blaze_story_id='555'").fetchone()[0])
    assert [x["n"] for x in it] == [1, 2] and len(it[0]["online"]) == 20000 and it[0]["anchor"] == "" and it[1] == {"n": 2, "online": "two", "anchor": "A"}
    assert s.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "555", "online": "o", "anchor": "a", "items": junk}]})[1]["updated"] == 0           # same: nothing written
    s.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "555", "online": "o", "anchor": "a"}]})                                                     # an older poller sends no items: what is stored stays
    assert json.loads(c.execute("SELECT script_items FROM stories WHERE blaze_story_id='555'").fetchone()[0]) == it
    assert s.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "555", "online": "o", "anchor": "a", "items": "nope"}]})[0] == 200

def test_the_database_gets_the_new_column_and_keeps_its_data(tmp_path):
    p = tmp_path / "v11.db"; c = sqlite3.connect(str(p)); c.executescript(dbm.SCHEMA)
    for v, t, col, typ, _ in dbm.COLUMNS:
        if v <= 11 and col not in {x[1] for x in c.execute("PRAGMA table_info(%s)" % t)}: c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, col, typ))
    c.execute("INSERT INTO rundowns(id, blaze_rundown_id, name) VALUES(1,'R1','News')"); c.execute("INSERT INTO stories(id, blaze_story_id, rundown_id, slug, online_script) VALUES(1,'724921',1,'SLUG','kept')")
    c.execute("PRAGMA user_version = 11"); c.commit(); c.close()
    d = dbm.DB(p); assert dbm.SCHEMA_VERSION >= 12 and d.conn.execute("SELECT online_script, script_items FROM stories").fetchone() == {"online_script": "kept", "script_items": None}

def test_the_middle_pane_has_a_box_per_item_the_wpm_input_and_the_selection_count():
    t = page(); mid = t[t.index("function renderMid("):t.index("function kvr(")]
    assert "scriptParts(c,tab)" in mid and 'el("div","sitem")' in mid and '"Item "+p.n' in mid           # one box per item, each with its own Copy
    assert 'lsGet("autoid_wpm")' in t and 'lb=el("label",null,"Words per minute")' in mid and "refreshWpm" in mid       # words per minute at the top, remembered
    assert 'addEventListener("selectionchange",selInfo)' in t and 'e.id="selinfo"' in t and ".selpop{position:fixed" in t
    assert "user-select:none" in t                                                                      # the box headers are never part of a selection

# ------------------------------------------------------------------ the real page against a real server, in a headless DOM
def test_the_middle_pane_in_a_headless_browser(tmp_path):
    import os, shutil, subprocess
    from test_server import Srv
    node = shutil.which("node"); js = ROOT / "tools" / "dev" / "check_script_items.js"
    if not node: pytest.skip("node is not installed (developer check only)")
    env = dict(os.environ); env["NODE_PATH"] = os.pathsep.join(p for p in [str(ROOT / "tools" / "dev" / "node_modules"), env.get("NODE_PATH", "")] if p)
    if subprocess.run([node, "-e", "require('jsdom')"], env=env, capture_output=True).returncode: pytest.skip("jsdom is not installed: cd tools/dev && npm install jsdom")
    s = Srv(tmp_path, "story_id"); assert s.login()[0] == 200
    st = [{"blaze_story_id": "1", "slug": "FIRST", "slug_id": "901", "position": 1, "story_title": "first story"}]
    assert s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "10", "rundown_name": "Bulletin", "stories": st})[0] == 200
    items = [{"n": 1, "online": "one two three four five six", "anchor": "a b c d"}, {"n": 2, "online": "seven eight", "anchor": ""}, {"n": 3, "online": "", "anchor": "x y z"}]
    assert s.svc("POST", "/svc/scripts", {"stories": [{"blaze_story_id": "1", "online": "one two three four five six\n\nseven eight", "anchor": "a b c d\n\nx y z", "items": items}]})[0] == 200
    r = subprocess.run([node, str(js), str(s.port), "admin@x.io", "adminpass1"], env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, r.stdout[-3000:] + r.stderr[-800:]
