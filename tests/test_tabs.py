"""v10.9.5: tabs. Rundown, Ready feed, Recent activity (last 1 / 2 / 4 hours) and Users are tabs of the header; the feed can still be pinned to the bottom."""
import sys, pathlib, time, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from test_server import Srv

ROOT = pathlib.Path(__file__).resolve().parents[1]
def page(): return (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
def iso(mins_ago): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - mins_ago * 60))

@pytest.fixture
def s(tmp_path):
    x = Srv(tmp_path, "story_id"); assert x.login()[0] == 200
    with x.app.db.tx() as cur:
        for name, ago in (("t_30min", 30), ("t_90min", 90), ("t_3h", 180), ("t_6h", 360)): cur.x("INSERT INTO events(time,actor,action,details) VALUES(?,?,?,?)", (iso(ago), "tester", name, json.dumps({"n": ago})))
    return x

def acts(s, q): st, r = s.call("GET", "/api/events" + q); assert st == 200, r; return [x["action"] for x in r if x["action"].startswith("t_")]

def test_the_events_call_keeps_the_last_hours(s):
    assert acts(s, "?limit=500&hours=1") == ["t_30min"]
    assert acts(s, "?limit=500&hours=2") == ["t_30min", "t_90min"]                      # newest first
    assert acts(s, "?limit=500&hours=4") == ["t_30min", "t_90min", "t_3h"]
    assert sorted(acts(s, "?limit=500")) == sorted(["t_30min", "t_90min", "t_3h", "t_6h"])      # without hours: the newest rows by id, as before
    assert acts(s, "?limit=500&hours=0.75") == ["t_30min"]

def test_the_hours_are_checked_and_the_log_stays_limited(s):
    for bad in ("0", "-1", "169", "abc"): assert s.call("GET", "/api/events?hours=" + bad)[0] == 400, bad
    assert s.call("GET", "/api/events?limit=x")[0] == 400
    st, r = s.call("GET", "/api/events?hours=4&limit=2"); assert st == 200 and len(r) == 2

def test_the_page_has_the_four_tabs_and_the_feed_can_still_be_pinned():
    t = page()
    for k in ('data-tab="rundown"', 'id="feedbtn" type="button" data-tab="feed"', 'data-tab="activity"', 'data-tab="users"', 'id="tab-rundown"', 'id="evh"', '<option value="1">1 hour</option><option value="2">2 hours</option><option value="4">4 hours</option>', 'id="feeddock"', "function syncTab", "function setTab", "async function loadTab", "#feed.tab{"): assert k in t, k
    assert t.index('id="tab-rundown"') < t.index('id="split"') < t.index('id="feed"') < t.index('id="deskbox"') < t.index('id="adminbox"')
    assert 'data-go="#adminbox"' not in t                                               # Settings scroll link is gone: Users is a tab

def test_only_the_tab_on_screen_asks_the_server_for_events_and_users():
    t = page(); body = t[t.index("async function loadTab"):t.index("function setMode()")]
    assert 'pgTab==="activity"&&can("events")' in body and 'pgTab==="users"&&can("users")' in body and "/api/events?limit=500&hours=" in body
    assert "/api/events" not in t[t.index("async function load()"):t.index("async function loadTab")]

# ------------------------------------------------------------------ the real page against a real server, in a headless DOM
def run_dom(s, kind, email, pw, tmp=None):
    import os, shutil, subprocess
    node = shutil.which("node"); js = ROOT / "tools" / "dev" / "check_tabs.js"
    if not node: pytest.skip("node is not installed (developer check only)")
    env = dict(os.environ); env["NODE_PATH"] = os.pathsep.join(p for p in [str(ROOT / "tools" / "dev" / "node_modules"), env.get("NODE_PATH", "")] if p)
    if subprocess.run([node, "-e", "require('jsdom')"], env=env, capture_output=True).returncode: pytest.skip("jsdom is not installed: cd tools/dev && npm install jsdom")
    r = subprocess.run([node, str(js), str(s.port), email, pw, kind], env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, r.stdout[-3000:] + r.stderr[-800:]

def test_the_tabs_in_a_headless_browser_as_admin(s):
    st = [{"blaze_story_id": str(i), "slug": "S%d" % i, "slug_id": str(900 + i), "position": i, "story_title": "story %d" % i} for i in range(1, 4)]
    assert s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "10", "rundown_name": "Bulletin", "stories": st})[0] == 200
    run_dom(s, "admin", "admin@x.io", "adminpass1")

def test_the_tabs_in_a_headless_browser_as_editor(s):
    st = [{"blaze_story_id": str(i), "slug": "S%d" % i, "slug_id": str(900 + i), "position": i, "story_title": "story %d" % i} for i in range(1, 4)]
    assert s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "10", "rundown_name": "Bulletin", "stories": st})[0] == 200
    code, r = s.call("POST", "/api/users", {"email": "ed@x.io", "password": "editorpass1", "role": "editor", "valid_upto": "2099-12-31"}); assert code in (200, 201), r
    run_dom(s, "editor", "ed@x.io", "editorpass1")
