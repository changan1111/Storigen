"""v10.2.0 Ready feed: a live list of the clips whose file is in Blaze's media list (NITRO green), so nobody has to watch the chip, and a push message to a chat when one becomes ready."""
import http.server, json, pathlib, sqlite3, sys, threading, time
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "tests"))
from test_server import sid, Srv                                                              # noqa: F401  (fixture)
from test_media_list_matching import env, slug, media, clips as poller_clips                  # noqa: F401  (fixtures and helpers of the poller tests)

def story_set(s, n=4, name="Morning Bulletin"):
    s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "R1", "rundown_name": name, "stories": [{"blaze_story_id": str(700000 + k), "slug": "STORY %d" % k, "story_title": "Story title %d" % k} for k in range(n)]})
    return {c["blaze_story_id"]: c for c in s.call("GET", "/api/clips")[1]["clips"]}

def media_found(s, did, mos, name=None):
    body = {"display_id": did, "media_id": mos}
    if name is not None: body["media_name"] = name
    return s.svc("POST", "/svc/media", body)

def feed(s, qs=""): return s.call("GET", "/api/feed" + qs)[1]
def sql(s, q, a=()):
    with s.app.db.tx() as cur: cur.x(q, a)

def test_feed_lists_only_clips_with_a_file_in_blazes_media_list_newest_first_with_every_field(sid):
    c = story_set(sid); assert feed(sid)["items"] == [] and feed(sid)["counts"]["all"] == 0
    media_found(sid, c["700000"]["display_id"], "MOS-A", "RAIN A.mxf"); sql(sid, "UPDATE clip_ids SET media_found_at='2026-01-01T00:00:00Z' WHERE display_id=?", (c["700000"]["display_id"],))   # make the first one clearly older
    media_found(sid, c["700002"]["display_id"], "MOS-C", "FIRE C.mxf")
    f = feed(sid); assert [i["blaze_story_id"] for i in f["items"]] == ["700002", "700000"] and f["total"] == 2 and f["counts"] == {"ready": 2, "attached": 0, "problem": 0, "all": 2}
    i = f["items"][0]; assert i["story"] == "Story title 2" and i["name_id"] == c["700002"]["name_id"] and i["mos_object_id"] == "MOS-C" and i["media_name"] == "FIRE C.mxf"
    assert i["bulletin"] == "Morning Bulletin" and i["status"] == "READY" and i["status_text"] == "Ready to attach" and i["ready_at"] and i["attached_at"] is None and i["reason"] is None
    assert i["blaze_rundown_id"] == "R1" and "position" in i and i["state"] and i["qa_state"] in (None, "") and i["typed"] is False       # v10.3.0: what the table's Quick test attach button needs

def test_feed_needs_a_login_and_checks_its_parameters(sid):
    assert sid.call("GET", "/api/feed", cookie=False)[0] == 401
    assert sid.call("GET", "/api/feed?status=zzz")[0] == 400 and sid.call("GET", "/api/feed?limit=abc")[0] == 400

def test_feed_search_finds_story_clip_story_id_mos_id_media_name_and_bulletin(sid):
    c = story_set(sid); media_found(sid, c["700000"]["display_id"], "MOS-777", "Rain Alert Coastal.mxf"); media_found(sid, c["700001"]["display_id"], "MOS-888", "Fire Drill.mxf")
    n = lambda q: [i["blaze_story_id"] for i in feed(sid, "?q=" + q)["items"]]
    assert n("rain") == ["700000"] and n("mos-888") == ["700001"] and n("700001") == ["700001"] and n("fire") == ["700001"] and sorted(n("morning")) == ["700000", "700001"]
    assert n(c["700000"]["name_id"].lower()) == ["700000"] and n("rain%20coastal") == ["700000"] and n("rain%20fire") == [] and n("zzz") == [] and n("%25") == []

def test_feed_status_words_counts_and_filters(sid):
    c = story_set(sid, 6); d = {k: v["display_id"] for k, v in c.items()}
    for k in d: media_found(sid, d[k], "M" + k)
    sql(sid, "UPDATE clip_ids SET state='ATTACHED', attached_at='2026-11-15T10:00:00Z' WHERE display_id=?", (d["700001"],))
    sql(sid, "UPDATE clip_ids SET qa_state='REQUESTED' WHERE display_id=?", (d["700002"],))
    sql(sid, "UPDATE clip_ids SET qa_state='BLOCKED', qa_msg='format 23 is not verified' WHERE display_id=?", (d["700003"],))
    sql(sid, "UPDATE clip_ids SET state='NEEDS_DESK', attach_error='two files match' WHERE display_id=?", (d["700004"],))
    sql(sid, "UPDATE clip_ids SET state='ATTACH_SUBMITTED' WHERE display_id=?", (d["700005"],))
    f = feed(sid); st = {i["blaze_story_id"]: i for i in f["items"]}
    assert {k: v["status"] for k, v in st.items()} == {"700000": "READY", "700001": "ATTACHED", "700002": "REQUESTED", "700003": "NOT_SENT", "700004": "NEEDS_DESK", "700005": "SUBMITTED"}
    assert st["700003"]["reason"] == "format 23 is not verified" and st["700004"]["reason"] == "two files match" and st["700001"]["attached_at"] == "2026-11-15T10:00:00Z"
    assert f["counts"] == {"ready": 3, "attached": 1, "problem": 2, "all": 6}
    ids = lambda q: sorted(i["blaze_story_id"] for i in feed(sid, q)["items"])
    assert ids("?status=ready") == ["700000", "700002", "700005"] and ids("?status=attached") == ["700001"] and ids("?status=problem") == ["700003", "700004"]
    assert feed(sid, "?status=attached&q=zzz")["counts"]["ready"] == 3            # the counts are for the whole day, whatever the search says

def test_feed_is_for_one_day_hides_removed_stories_and_honours_limit(sid):
    c = story_set(sid, 5)
    for k in c: media_found(sid, c[k]["display_id"], "M" + k)
    sql(sid, "UPDATE stories SET deleted=1 WHERE blaze_story_id='700004'")
    f = feed(sid); assert f["total"] == 4 and "700004" not in [i["blaze_story_id"] for i in f["items"]]
    assert len(feed(sid, "?limit=2")["items"]) == 2 and feed(sid, "?limit=2")["total"] == 4
    assert feed(sid, "?day=20200101")["items"] == [] and feed(sid, "?day=20200101")["counts"]["all"] == 0

def test_media_name_is_kept_and_a_repeat_or_name_backfill_is_not_a_new_event(sid):
    c = story_set(sid); did = c["700000"]["display_id"]; media_found(sid, did, "M1"); media_found(sid, did, "M1"); media_found(sid, did, "M1", "Rain.mxf"); media_found(sid, did, "M1", "")
    ev = [e for e in sid.call("GET", "/api/events?limit=50")[1] if e["action"] == "media_found"]
    assert len(ev) == 1 and feed(sid)["items"][0]["media_name"] == "Rain.mxf"                 # one event; the name arrived later and an empty name did not erase it
    media_found(sid, did, "M2", "Rain v2.mxf"); ev = [e for e in sid.call("GET", "/api/events?limit=50")[1] if e["action"] == "media_found"]
    assert len(ev) == 2 and feed(sid)["items"][0]["mos_object_id"] == "M2"                    # a replaced file is news again

class Hook:
    """A tiny chat webhook that records what is posted to it."""
    def __init__(self):
        self.got = []; me = self
        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self): me.got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"])))); self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
            def log_message(self, *a): pass
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H); self.url = "http://127.0.0.1:%d/hook" % self.srv.server_address[1]; threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def wait(self, n, secs=3):
        end = time.time() + secs
        while len(self.got) < n and time.time() < end: time.sleep(0.02)
        time.sleep(0.15); return self.got

def test_a_chat_message_is_pushed_once_when_a_clip_becomes_ready(sid, monkeypatch):
    hook = Hook(); monkeypatch.setenv("READY_WEBHOOK_URL", hook.url); c = story_set(sid); did = c["700000"]["display_id"]
    media_found(sid, did, "MOS-42", "Rain Alert.mxf"); got = hook.wait(1); assert len(got) == 1
    t = got[0]["text"]; assert t.startswith("READY on Nitro: Story title 0") and c["700000"]["name_id"] in t and "MOS MOS-42" in t and "media Rain Alert.mxf" in t and "Morning Bulletin" in t
    media_found(sid, did, "MOS-42", "Rain Alert.mxf"); media_found(sid, did, "MOS-42", "Rain Alert (renamed).mxf"); assert len(hook.wait(2, 0.6)) == 1       # same file again, or only a new name: nothing more to say
    media_found(sid, did, "MOS-43", "Rain Alert v2.mxf"); assert len(hook.wait(2)) == 2 and "MOS MOS-43" in hook.got[1]["text"]                  # a replaced file is news

def test_no_message_for_a_clip_already_in_the_story_or_without_a_webhook(sid, monkeypatch):
    hook = Hook(); c = story_set(sid, 3)
    media_found(sid, c["700000"]["display_id"], "M0")                                           # READY_WEBHOOK_URL is not set: nothing is sent, nothing breaks
    monkeypatch.setenv("READY_WEBHOOK_URL", hook.url); sql(sid, "UPDATE clip_ids SET state='ATTACHED' WHERE display_id=?", (c["700001"]["display_id"],))
    media_found(sid, c["700001"]["display_id"], "M1"); assert hook.wait(1, 0.6) == []             # the desk already attached it: nobody needs telling
    media_found(sid, c["700002"]["display_id"], "M2"); assert len(hook.wait(1)) == 1
    monkeypatch.setenv("READY_WEBHOOK_URL", "http://127.0.0.1:9/unreachable"); c2 = story_set(sid, 4)
    assert media_found(sid, c2["700003"]["display_id"], "M3")[0] == 200                           # a dead webhook never breaks the poller's call

def test_the_poller_sends_the_media_name_and_tells_a_clip_again_once_to_backfill_it(env):
    s, f, p = env; assert s.login()[0] == 200; f.slugs = [slug(1, "A", 1)]; p.cycle(); did = poller_clips(s)[0]["display_id"]
    f.medias = [media(77, did[:14] + "_A.mxf")]; p.cycle(); i = feed(s)["items"][0]
    assert i["mos_object_id"] == "77" and i["media_name"].endswith("_A.mxf") and i["status"] == "READY"
    sql(s, "UPDATE clip_ids SET media_name=NULL WHERE display_id=?", (did,)); p.led.put("media:" + did, "77")          # what an install made before 10.2.0 had remembered: the id only
    p.cycle(); assert feed(s)["items"][0]["media_name"].endswith("_A.mxf")
    assert len([e for e in s.call("GET", "/api/events?limit=50")[1] if e["action"] == "media_found"]) == 1             # the backfill made no second event (so no second chat message)
    assert p.led.get("media:" + did).startswith("77|") and p.led.get("media:" + did).endswith("_A.mxf")                # remembered with its name now, so the next round sends nothing again

H = (root / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
def test_the_page_has_the_feed_button_drawer_search_and_notify_option():
    for k in ('id="feedbtn"', 'id="feed"', 'id="fq"', 'id="fst"', 'id="fnote"', 'id="flist"', 'id="fsum"', 'id="toasts"', "Ready feed"): assert k in H, k
    for k in ("function loadFeed", "function renderFeed", "function feedRow", "function feedNotify", "function openFeed", "function closeFeed", "function feedJump"): assert k in H, k
    assert "await loadFeed();" in H and "/api/feed?" in H and "Notification.requestPermission" in H and 'e.key==="f"' in H
    a = H.index("function feedRow"); b = H.index("function feedJump"); assert "innerHTML" not in H[a:b]            # story and media names are shown as text, never as markup

def test_the_feed_is_a_table_newest_first_with_a_quick_test_button_and_a_reliable_story_jump():
    r = H[H.index("const fmtHMS"):H.index("async function feedJump")]
    for k in ('el("table")', 'el("thead")', 'el("tbody")', 'el("tr"', 'el("td"', 'el("th"', "Ready at", "Clip ID", "Blaze story ID", "MOS object ID", "Media", "Bulletin", "Quick test"): assert k in r, k
    assert "quickAttach(c)" in r and "qaWhyAll(c)" in r and 'can("attach")' in r                      # the SAME Yes / No box and the SAME rules as on the story card
    assert 'localeCompare' in H[H.index("function loadFeed"):H.index("function feedRow")]            # newest first, enforced in the page too
    j = H[H.index("async function feedJump"):]; j = j[:j.index("\nfunction ")]
    assert 'filter="all"' in j and 'qtext=""' in j and "setShow(it.blaze_rundown_id" in j and "openStory(it.id)" in j       # no filter, search or other bulletin can hide the story
    q = H[H.index("function quickAttach"):]; assert "z-index:80" in q[:q.index("\nfunction ")]       # the Yes / No box is above the wide feed panel

def test_the_feed_does_not_rebuild_what_did_not_change_and_does_not_flood_on_first_look():
    a = H.index("function loadFeed"); b = H.index("function feedRow"); load = H[a:b]
    assert "feed.seen===null||feed.day!==a.day" in load and "feed.seen=new Set(" in load                          # the first look at a day is not news
    r = H[H.index("function renderFeed"):H.index("function feedJump")]; assert 'changed("feed"' in r and r.index("if(!feed.open)return") < r.index('changed("feed"')

def test_a_database_made_by_10_1_upgrades_to_get_the_media_name_column_and_keeps_its_data(tmp_path):
    from autoid_lite import db as dbm
    p = tmp_path / "v7.db"; c = sqlite3.connect(str(p)); c.executescript(dbm.SCHEMA)
    for v, t, col, typ, _ in dbm.COLUMNS:
        if v <= 7 and col not in {x[1] for x in c.execute("PRAGMA table_info(%s)" % t)}: c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, col, typ))
    c.execute("INSERT INTO rundowns(id, blaze_rundown_id, name, air_date) VALUES(1,'R1','News','2026-11-13')"); c.execute("INSERT INTO stories(id, blaze_story_id, rundown_id, slug) VALUES(1,'724921',1,'SLUG')")
    c.execute("INSERT INTO clip_ids(id, display_id, day, seq, story_id, state, media_id, media_found_at) VALUES(1,'D1','2026-11-13',1,1,'ON_NITRO','M1','2026-11-13T10:00:00Z')"); c.execute("PRAGMA user_version = 7"); c.commit(); c.close()
    d = dbm.DB(p); r = d.conn.execute("SELECT display_id, media_id, media_name FROM clip_ids").fetchone()
    assert r == {"display_id": "D1", "media_id": "M1", "media_name": None} and d.conn.execute("PRAGMA user_version").fetchone()["user_version"] == dbm.SCHEMA_VERSION >= 8


def test_feed_has_minimize_and_maximize_and_does_not_cover_the_page_by_default():
    for k in ('id="feedmin"', 'id="feedmax"', 'id="fhs"', "function feedMode", "body.fd-dock{padding-bottom", "#feed.min", "#feed.max"): assert k in H, k
