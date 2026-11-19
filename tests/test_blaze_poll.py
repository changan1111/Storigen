"""The Blaze poller against a fake Blaze (real HTTP) and the real Auto-ID server: stories are synced, clips are found, nothing is ever written to Blaze."""
import os as _os; _os.environ.setdefault("ID_FORMAT", "legacy")      # these tests pin the legacy YYYYMMDD_NNNNC_ ID; test_clip_names_and_versions.py covers DDMMYY_STORY_NAME
import re, time, datetime as dt, importlib.util, json, pathlib, sys, threading, http.server
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "tests"))
from test_server import Srv
spec = importlib.util.spec_from_file_location("blaze_poll", root / "tools" / "blaze_poll.py"); bp = importlib.util.module_from_spec(spec); spec.loader.exec_module(bp)

class Fake:
    """Pretends to be Blaze's DataService. Records every request so a test can prove nothing but reads (and the session ping) happened."""
    def __init__(self):
        self.slugs, self.medias, self.story_clips, self.log, self.expired, self.linked = [], [], {}, [], False, {}
        self.show_list, self.slugs_by_show, self.puts, self.script_dur, self.clip_dur, self.obj_ids = [], {}, [], {}, {}, {}
        self.story_titles, self.active, self.max_active, self.glock = {}, 0, 0, threading.Lock(); self.story_items = {}; self.story_extra = {}      # story ID -> extra storyComplete fields (createdBy, assignedTo ...) when a test wants them; story ID -> the items of versions[0] (with text1 / text2) when a test wants its own
        self.fail_shows, self.hang_shows, self.hang_secs, self.delay, self.expired_404, self.ident_calls = set(), set(), 0.0, 0.0, False, []     # failure, timeout and latency injection
        self.forms, self.post_mode = [], "ok"; self.logins, self.login_mode, self.cookies, self.new_sid = [], "ok", [], "NEWSID"; self.media_total, self.fail_list = None, False          # post_mode: ok | refuse (400) | noop (201 but nothing added) | double (adds the clip twice)
        outer = self
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def reply(self, obj, ctype="application/json", code=200):
                b = (obj if isinstance(obj, str) else json.dumps(obj)).encode()
                try: self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
                except (BrokenPipeError, ConnectionResetError): pass                # the client gave up (a timeout test)
            def do_PUT(self):
                import urllib.parse as up; outer.log.append(("PUT", self.path)); n = int(self.headers.get("Content-Length") or 0); form = {k: v[0] for k, v in up.parse_qs(self.rfile.read(n).decode()).items()}
                m = re.match(r"^/DataService/stories/(\d+)/versions/(\d+)$", self.path.split("?")[0])
                if m: outer.puts.append((m.group(1), m.group(2), form)); outer.script_dur[m.group(1)] = int(form.get("scriptDur", 0))
                self.reply("", "text/plain")
            def do_POST(self):
                import urllib.parse as up; outer.log.append(("POST", self.path)); n = int(self.headers.get("Content-Length") or 0); form = {k: v[0] for k, v in up.parse_qs(self.rfile.read(n).decode()).items()}; outer.forms.append(form)
                if self.path.split("?")[0] == "/DataService/sessions":              # the login, as captured: 201, empty body, the session in Set-Cookie and Location
                    outer.logins.append(form)
                    if outer.login_mode == "refuse": return self.reply({"errors": ["bad credentials"]}, code=401)
                    self.send_response(201); self.send_header("Content-Length", "0")
                    if outer.login_mode in ("ok", "cookie"): self.send_header("Set-Cookie", "sessionId=%s;Version=1" % outer.new_sid)
                    if outer.login_mode in ("ok", "location"): self.send_header("Location", "http://127.0.0.1/DataService/sessions/%s" % outer.new_sid)
                    self.end_headers(); outer.expired = False; outer.expired_404 = False; return
                sid = self.path.split("/")[3] if self.path.startswith("/DataService/stories/") else None
                if sid is None or not form.get("mosObjectId"): return self.reply({})
                if outer.post_mode == "refuse": return self.reply({"error": "story is locked"}, code=400)
                if outer.post_mode in ("ok", "double"):
                    for _ in range(2 if outer.post_mode == "double" else 1): outer.story_clips.setdefault(sid, []).append((int(form["mosObjectId"]), form["title"]))
                self.reply({"story_status": "READY", "clip_status": "READY"}, code=201)
            def do_DELETE(self):
                outer.log.append(("DELETE", self.path)); parts = self.path.split("?")[0].split("/"); sid, cid = parts[3], int(parts[5]); cl = outer.story_clips.get(sid, [])
                if 0 <= cid - int(sid) * 100 < len(cl): cl.pop(cid - int(sid) * 100)
                self.reply({"story_status": "READY", "clip_status": "READY", "duration": 0, "itemId": 900001, "deletedClipDur": 50000})
            def do_GET(self):
                outer.log.append(("GET", self.path)); outer.cookies.append(self.headers.get("Cookie")); p = self.path.split("?")[0]
                if outer.expired: return self.reply("<html>login</html>", "text/html")
                if outer.expired_404: return self.reply({"errors": [" authenticationFailed"]}, code=404)         # what the Blaze capture shows for an expired session
                if outer.delay:
                    with outer.glock: outer.active += 1; outer.max_active = max(outer.max_active, outer.active)      # how many requests are in flight at once
                    time.sleep(outer.delay)
                    with outer.glock: outer.active -= 1
                mm = re.match(r"^/DataService/shows/(\d+)/slugs$", p)
                if mm and mm.group(1) in outer.fail_shows: return self.reply({"errors": ["boom"]}, code=500)
                if mm and mm.group(1) in outer.hang_shows: time.sleep(outer.hang_secs); return self.reply({"slugs": []})
                mc = re.match(r"^/DataService/stories/(\d+)/clips$", p)
                if mc:
                    outer.ident_calls.append(mc.group(1)); sid = mc.group(1)
                    return self.reply({"clips": [{"id": int(sid) * 100 + k, "clipType": "MEDIA", "mosObjectId": {"id": i}, "objId": outer.obj_ids.get(i, "obj%s" % i), "title": t, "duration": outer.clip_dur.get(i, 50000), "position": k + 1, "status": "READY"} for k, (i, t) in enumerate(outer.story_clips.get(sid, []))]})
                if p.endswith("/slugs"): return self.reply({"slugs": outer.slugs_by_show.get(p.split("/")[3], outer.slugs)})
                if p == "/DataService/shows": return self.reply({"shows": outer.show_list})
                if p.startswith("/DataService/shows/"): return self.reply({"shows": {"id": 34427, "title": "05_11_14:30 PM Bulletin"}})
                if p == "/DataService/mosobjects":
                    if outer.fail_list and "%22title%22" not in self.path: return self.reply({"errors": ["boom"]}, code=500)        # the list call (no title filter) fails, title searches still work
                    import json as _j, urllib.parse as _u
                    try: flt = _j.loads((_u.parse_qs(_u.urlparse(self.path).query).get("filter") or ["{}"])[0])
                    except ValueError: flt = {}
                    ms = outer.medias; gk = getattr(outer, "group_key", None)
                    if gk is not None:                                                  # v10.9.3: a Blaze that keeps NEWS in the plain list and knows the group filter field `gk`
                        if gk in flt: ms = [m for m in ms if m.get("objGroup") == flt[gk]]
                        else: ms = [m for m in ms if m.get("objGroup") == "NEWS"]       # no group named, or a filter field Blaze does not know (ignored): the plain NEWS list comes back
                    if flt.get("title"): ms = [m for m in ms if flt["title"].lower() in (m.get("title") or "").lower()]
                    return self.reply({"results": {"assetsPerPage": 50, "medias": ms, "totalResults": outer.media_total if (gk is None and outer.media_total is not None) else len(ms)}})
                if p.startswith("/DataService/sessions/"): return self.reply({"user": {"id": 1}})
                if p.endswith("/complete/"):
                    sid = p.split("/")[3]; return self.reply({"storyComplete": {**outer.story_extra.get(sid, {}), "title": outer.story_titles.get(sid, "T" + sid), "shows": [{"id": 34427}] + [{"id": x} for x in outer.linked.get(sid, [])], "versions": [{"id": 1, "scriptDur": outer.script_dur.get(sid, 0), "wpm": 100, "items": outer.story_items.get(sid) or [{"id": 900002, "arrangeOrder": 2}, {"id": 900001, "arrangeOrder": 1}]}], "clips": [{"id": int(sid) * 100 + k, "mosObjectId": {"id": i}, "title": t, "duration": outer.clip_dur.get(i, 50000), "itemId": 900001} for k, (i, t) in enumerate(outer.story_clips.get(sid, []))]}})
                self.reply({})
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); self.httpd.daemon_threads = True; self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

def slug(story, title, pos, fmt=20): return {"id": story + 1000, "slugTitle": title, "finalPosition": pos, "deleted": 0, "storyId": {"id": story, "storyFormatId": {"id": fmt}}}
def media(mid, title, secs_ago=600, ms=50880):
    t = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=secs_ago)).astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat(timespec="seconds")
    return {"id": mid, "title": title, "description": title, "duration": ms, "modifiedDate": t, "objGroup": "NEWS", "status": "UPDATED"}

@pytest.fixture
def env(tmp_path):
    s = Srv(tmp_path, "story_id"); f = Fake()
    cfg = bp.Cfg({"BLAZE_URL": "http://127.0.0.1:%d" % f.port, "BLAZE_SESSION_ID": "SID", "BLAZE_USERNAME": "u", "BLAZE_SHOW_IDS": "34427",
                  "WEB_PORT": str(s.port), "SERVICE_API_KEY": "k" * 20, "BLAZE_MEDIA_SETTLE_SECS": "60",
                  "BLAZE_LEDGER": str(tmp_path / "ledger.db"), "BLAZE_REPORT_DIR": str(tmp_path / "reports"), "BLAZE_IGNORE_TITLES": "BREAK,OPEN MONTAGE", "BLAZE_MEDIA_RETRY_SECS": "0", "BLAZE_INFO_SECS": "0", "BLAZE_MEDIA_GROUPS": "NONE"})
    return s, f, bp.Poller(cfg)

def clips(s):
    from test_server import KEY
    return s.svc("GET", "/svc/clips")[1]

def test_stories_are_synced_and_the_clip_id_comes_from_the_story_id(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14), slug(724905, "AUTO ID 03", 13)]
    p.cycle(); rows = clips(s)
    assert {r["blaze_story_id"] for r in rows} == {"724921", "724905"} and all(r["blaze_rundown_id"] == "34427" for r in rows)
    ids = {r["blaze_story_id"]: r["display_id"] for r in rows}; p.cycle(); assert {r["blaze_story_id"]: r["display_id"] for r in clips(s)} == ids      # same story = same ID
    assert s.app.compute_health  # server still healthy

def test_an_empty_answer_from_blaze_never_wipes_the_registry(env):
    s, f, p = env; f.slugs = [slug(1, "A", 1)]; p.cycle(); f.slugs = []; p.cycle()
    assert len(clips(s)) == 1 and not clips(s)[0]["deleted"]

def test_finished_file_is_found_and_the_attach_call_is_only_printed(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); did = clips(s)[0]["display_id"]
    f.medias = [media(1103586, did[:14] + "_SVO TVT FISHERMAN.mxf"), media(1, "051126_OTHER.mxf")]
    out = p.cycle(); assert out[0]["result"] == "found" and "GOING TO ATTACH" in out[0]["note"] and "order=15 itemId=900001" in out[0]["note"] and "mosObjectId=1103586" in out[0]["note"] and "duration=50&" in out[0]["note"]
    assert "order=15&itemId=900001" in out[0]["note"]
    assert not [x for x in f.log if x[0] == "POST"], "phase 1 must never write to Blaze"

def test_file_still_changing_missing_ambiguous_and_already_attached(env):
    s, f, p = env; f.slugs = [slug(10, "A", 1), slug(11, "B", 2), slug(12, "C", 3), slug(13, "D", 4)]; p.cycle()
    d = {r["blaze_story_id"]: r["display_id"][:14] for r in clips(s)}
    f.medias = [media(5, d["10"] + "_X.mxf", secs_ago=5), media(6, d["12"] + "_X.mxf"), media(7, d["12"] + "_Y.mxf"), media(8, d["13"] + "_Z.mxf")]
    f.story_clips = {"13": [(8, d["13"] + "_Z.mxf")]}
    r = {x["story"]: x for x in p.cycle()}
    assert r["10"]["result"] == "settling" and r["11"]["result"] == "missing" and r["12"]["result"] == "ambiguous" and "ALREADY IN STORY" in r["13"]["note"]

def test_versions_are_matched_separately():
    k1, k2 = bp.clip_key("20261105_0001U_SLUG", 1), bp.clip_key("20261105_0001U_SLUG_V2", 2)
    assert bp.media_key("20261105_0001U_ANYTHING.mxf") == k1 and bp.media_key("20261105_0001U_ANYTHING_V2.mxf") == k2 and k1 != k2
    assert bp.media_key("SVO TVT KASIMEDU.mxf") is None and bp.media_key("12112026_HL TNI MULLAI.mxf") is None, "no ID at the start"
    assert bp.media_key("051126_SVO TVT KASIMEDU.mxf") == ("051126_SVO_TVT_KASIMEDU", 1), "DDMMYY_NAME is an ID since v9.7"

def test_expired_session_is_reported_not_treated_as_empty(env):
    s, f, p = env; f.slugs = [slug(1, "A", 1)]; p.cycle(); f.expired = True
    with pytest.raises(bp.SessionExpired): p.cycle()
    assert len(clips(s)) == 1 and not clips(s)[0]["deleted"]

def test_show_slug_and_story_ids_are_all_mapped(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); r = clips(s)[0]
    assert (r["blaze_rundown_id"], r["slug_id"], r["blaze_story_id"], r["position"]) == ("34427", "725921", "724921", 14)
    f.slugs = [slug(724921, "AUTO ID 05", 3)]; p.cycle(); r = clips(s)[0]; assert r["position"] == 3 and len(clips(s)) == 1        # a move updates the position only

def test_old_database_gets_the_new_columns(tmp_path):
    import sqlite3
    from autoid_lite.db import DB
    c = sqlite3.connect(str(tmp_path / "old.db")); c.execute("CREATE TABLE stories(id INTEGER PRIMARY KEY, blaze_story_id TEXT NOT NULL, rundown_id INTEGER NOT NULL, slug TEXT, last_seen_at TEXT, deleted INTEGER NOT NULL DEFAULT 0, deleted_at TEXT, deleted_reason TEXT)"); c.commit(); c.close()
    d = DB(tmp_path / "old.db"); assert {"slug_id", "position"} <= {r["name"] for r in d.conn.execute("PRAGMA table_info(stories)").fetchall()}


def set_state(s, did, state):
    with s.app.db.tx() as cur: cur.x("UPDATE clip_ids SET state=? WHERE display_id=?", (state, did))

def test_template_rows_get_no_id(env):
    s, f, p = env; f.slugs = [slug(1, "OPEN MONTAGE", 1), slug(2, "BREAK1", 2), slug(3, "BREAK 22", 3), slug(4, "BREAKING NEWS FLOOD", 4), slug(5, "Real story", 5)]; p.cycle()
    assert sorted(r["blaze_story_id"] for r in clips(s)) == ["4", "5"]       # BREAKING NEWS is a real story: only whole-title matches are skipped

def test_desk_attach_is_seen_confirmed_and_agrees_with_the_tool(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); did = clips(s)[0]["display_id"]; set_state(s, did, "ON_NITRO")
    f.medias = [media(1103586, did[:14] + "_SVO.mxf")]; p.cycle()                                  # the tool finds the file and plans (prints) the attach
    f.story_clips = {"724921": [(1103586, did[:14] + "_SVO.mxf")]}                                    # the desk attaches with the paperclip
    p.last_rec = 0; p.cycle()
    assert clips(s)[0]["state"] == "ATTACHED"                                                         # read back from Blaze, nothing written to it
    txt = p.report(write=True); assert "AGREE 1" in txt and "100%" in txt
    import csv; rows = list(csv.DictReader(open(pathlib.Path(p.c.reports) / ("agreement_%s.csv" % p.server_day().strftime("%Y%m%d")), encoding="utf-8-sig")))
    assert rows[0]["status"] == "AGREE" and rows[0]["tool_media"] == "1103586" and rows[0]["desk_media"] == "1103586"
    assert not [x for x in f.log if x[0] == "POST"]

def test_desk_attached_a_different_file_or_to_another_story_is_reported(env):
    s, f, p = env; f.slugs = [slug(10, "A", 1), slug(11, "B", 2)]; p.cycle(); d = {r["blaze_story_id"]: r["display_id"] for r in clips(s)}
    f.medias = [media(100, d["10"][:14] + "_X.mxf"), media(200, d["11"][:14] + "_Y.mxf")]; p.cycle()
    f.story_clips = {"10": [(999, d["10"][:14] + "_OTHERFILE.mxf")], "10b": [], "12": [(200, d["11"][:14] + "_Y.mxf")]}   # A: different file; B's file went into some other story
    f.slugs.append(slug(12, "C", 3)); p.cycle(); p.last_rec = 0; p.cycle()
    txt = p.report(write=False); assert "DISAGREE" in txt and "WRONG_STORY" in txt and "0%" in txt

def test_report_classes_without_a_server():
    import tempfile; led = bl_ledger = sys.modules["blaze_ledger"].Ledger(pathlib.Path(tempfile.mkdtemp()) / "l.db"); bl = sys.modules["blaze_ledger"]; now = 10_000.0
    clip = lambda n: {"display_id": n, "blaze_story_id": "S" + n, "blaze_rundown_id": "1"}
    led.plan("a", "Sa", "1", 1, "a.mxf", now - 5000); led.seen("a", "Sa", "1", 1, "a.mxf", 1, now - 4000)            # tool and desk agree
    led.plan("b", "Sb", "1", 2, "b.mxf", now - 5000); led.seen("b", "Sb", "1", 9, "b2.mxf", 1, now - 4000)           # desk picked another file
    led.seen("c", "Sc", "1", 3, "c.mxf", 1, now - 4000)                                                              # tool never found it
    led.plan("d", "Sd", "1", 4, "d.mxf", now - 5000); led.seen("d", "Sd", "1", 4, "d.mxf", 2, now - 4000)           # attached twice
    led.plan("e", "Se", "1", 5, "e.mxf", now - 5000)                                                                  # found long ago, nobody attached
    led.plan("f", "Sf", "1", 6, "f.mxf", now - 30)                                                                    # found just now
    res, summ = bl.build(led, [clip(x) for x in "abcdefg"], now=now)
    assert {o["display_id"]: o["status"] for o in res} == {"a": "AGREE", "b": "DISAGREE", "c": "TOOL_MISSED", "d": "DUPLICATE", "e": "OVERDUE", "f": "WAITING", "g": "NO_FILE"}
    assert summ["decided"] == 4 and abs(summ["rate"] - 0.25) < 1e-9                                                  # OVERDUE, WAITING, NO_FILE are not counted against the rate

def test_daily_report_is_written_once_when_the_day_changes(env):
    s, f, p = env; f.slugs = [slug(1, "A", 1)]; p.cycle()                                           # first ever run: remembers today, writes nothing
    assert not pathlib.Path(p.c.reports).exists() or not list(pathlib.Path(p.c.reports).glob("*.csv"))
    p.led.put("last_report_day", (p.server_day() - dt.timedelta(days=1)).isoformat()); p.cycle()
    files = list(pathlib.Path(p.c.reports).glob("agreement_*.csv")); assert len(files) == 1 and files[0].name == "agreement_%s.csv" % (p.server_day() - dt.timedelta(days=1)).strftime("%Y%m%d")
    p.cycle(); assert len(list(pathlib.Path(p.c.reports).glob("agreement_*.csv"))) == 1                # not again on the next pass


def test_only_chosen_story_formats_get_ids(env):
    s, f, p = env; p.c.only_formats = {"20", "21", "23", "27"}
    f.slugs = [slug(1, "HL - FLOOD 10 AM", 1, 25), slug(2, "VO FLOOD", 2, 20), slug(3, "THAMIZHAGAM ETTUTHIKKUM", 3, 27), slug(4, "BREAK3", 4, 27), slug(5, "CLOSE HEADLINE", 5, 25), slug(6, "PKG X", 6, 23)]
    p.cycle(); assert sorted(r["blaze_story_id"] for r in clips(s)) == ["2", "3", "6"]       # headline rows and template rows are left out, a real Montage story is kept


def watch_lines(p): 
    f = pathlib.Path(p.c.watchlog); return f.read_text(encoding="utf-8").splitlines() if f.exists() else []

def test_going_to_attach_line_names_clip_story_order_item_and_sends_nothing(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); did = clips(s)[0]["display_id"]
    f.medias = [media(1103586, did[:14] + "_SVO TVT FISHERMAN.mxf")]; p.cycle(); p.cycle()
    L = [x for x in watch_lines(p) if "GOING TO ATTACH" in x]; assert len(L) == 1, "announced once, not every pass"
    assert did in L[0] and 'story 724921 "AUTO ID 05"' in L[0] and "show 34427 05_11_14:30 PM Bulletin" in L[0] and "row 14" in L[0] and "media 1103586" in L[0] and "50s" in L[0]
    assert "order=15 itemId=900001" in L[0] and "DRY RUN" in L[0] and "CHECK" not in L[0]          # lowest arrangeOrder item, position + 1
    assert any("would send: POST /DataService/stories/724921/clips/" in x for x in watch_lines(p)) and not [x for x in f.log if x[0] == "POST"]

def test_ready_on_nitro_line_is_written_once_even_after_a_restart(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); did = clips(s)[0]["display_id"]
    assert not [x for x in watch_lines(p) if "READY ON NITRO" in x]; set_state(s, did, "ON_NITRO"); p.cycle(); p.cycle()
    L = [x for x in watch_lines(p) if "READY ON NITRO" in x]; assert len(L) == 1 and did in L[0] and "ready for story 724921" in L[0] and "show 34427" in L[0]
    p2 = bp.Poller(p.c); p2.cycle(); assert len([x for x in watch_lines(p2) if "READY ON NITRO" in x]) == 1

def test_media_is_searched_by_the_clip_id_not_by_scanning_one_page(env):
    s, f, p = env; p.c.media_mode = "search"; f.slugs = [slug(1, "A", 1)]; p.cycle(); did = clips(s)[0]["display_id"]; set_state(s, did, "ON_NITRO"); p.cycle()
    import urllib.parse as up; q = [up.unquote(x[1]) for x in f.log if x[1].startswith("/DataService/mosobjects")]
    key = bp.clip_key(did, 1)[0]          # the poller's own search key (the ID without version/check letters), whatever CHECK_CHAR other tests set
    assert q and all('"title":"%s"' % key in x and "assetsPerPage=50" in x and "pageNo=1" in x for x in q)

def test_unverified_format_and_linked_story_are_flagged_in_the_line(env):
    s, f, p = env; f.slugs = [slug(20, "PKG X", 1, 23), slug(21, "ANC Y", 2, 20)]; f.linked = {"21": [34500]}; p.cycle(); d = {r["blaze_story_id"]: r["display_id"] for r in clips(s)}
    f.medias = [media(5, d["20"][:14] + "_X.mxf"), media(6, d["21"][:14] + "_Y.mxf")]; p.cycle(); L = watch_lines(p)
    assert any(d["20"] in x and "not yet verified for story format 23" in x for x in L) and any(d["21"] in x and "SHARED story: it sits in shows 34427,34500" in x and "CHECK: story is linked" not in x for x in L)        # v10.4.0: a shared story is a note, not a flag

def test_file_already_in_the_story_is_logged_as_nothing_to_do(env):
    s, f, p = env; f.slugs = [slug(13, "D", 1)]; p.cycle(); did = clips(s)[0]["display_id"]
    f.medias = [media(8, did[:14] + "_Z.mxf")]; f.story_clips = {"13": [(8, did[:14] + "_Z.mxf")]}; p.cycle()
    assert any("ALREADY IN STORY" in x and did in x for x in watch_lines(p)) and not any("GOING TO ATTACH" in x for x in watch_lines(p))

def test_heartbeat_modes_and_live_attach_is_refused(env):
    s, f, p = env; p.b.ping(); sess = [x[0] for x in f.log if x[1].startswith("/DataService/sessions/")]; assert sess == ["GET"]       # default: GET only, as the Blaze page does (a PUT was never seen from it)
    c2 = bp.Cfg({"BLAZE_HEARTBEAT": "both"}); assert c2.heartbeat == "both"
    c = bp.Cfg({"BLAZE_HEARTBEAT": "get"}); assert c.heartbeat == "get"
    with pytest.raises(SystemExit): bp.Cfg({"BLAZE_ATTACH": "sometimes"})
    with pytest.raises(SystemExit): bp.Cfg({"BLAZE_HEARTBEAT": "x"})

def test_summary_table_covers_the_last_days(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); did = clips(s)[0]["display_id"]; set_state(s, did, "ON_NITRO")
    f.medias = [media(1103586, did[:14] + "_SVO.mxf")]; p.cycle(); f.story_clips = {"724921": [(1103586, did[:14] + "_SVO.mxf")]}; p.last_rec = 0; p.cycle()
    t = p.summary(5); assert "last 5 days" in t and "agreement 100% of 1" in t and "total: 100% of 1 attached clips on 1 day(s)" in t and len(t.splitlines()) == 7


# ================= live attach (OFF by default; every lock and guard is tested against the fake Blaze) =================
LIVE = {"BLAZE_ATTACH": "live", "BLAZE_LIVE_SHOW_IDS": "34427", "BLAZE_LIVE_CONFIRM": "YES_ATTACH_FOR_REAL"}

def live_env(tmp_path, **extra):
    s = Srv(tmp_path, "story_id"); f = Fake()
    e = {"BLAZE_URL": "http://127.0.0.1:%d" % f.port, "BLAZE_SESSION_ID": "SID", "BLAZE_USERNAME": "u", "BLAZE_SHOW_IDS": "34427", "WEB_PORT": str(s.port), "SERVICE_API_KEY": "k" * 20,
         "BLAZE_MEDIA_SETTLE_SECS": "60", "BLAZE_MEDIA_RETRY_SECS": "0", "BLAZE_INFO_SECS": "0", "BLAZE_LEDGER": str(tmp_path / "ledger.db"), "BLAZE_REPORT_DIR": str(tmp_path / "reports"),
         "BLAZE_LIVE_STOP_FILE": str(tmp_path / "STOP_LIVE"), **LIVE, **extra}
    return s, f, bp.Poller(bp.Cfg(e)), e

def posts(f): return [x for x in f.forms if x.get("mosObjectId")]
def ready_clip(s, f, p, story=724921, title="AUTO ID 05", pos=14, fmt=20, mid=1103586):
    f.slugs = f.slugs + [slug(story, title, pos, fmt)]; p.cycle(); did = [r for r in clips(s) if r["blaze_story_id"] == str(story)][0]["display_id"]
    set_state(s, did, "ON_NITRO"); f.medias.append(media(mid, did[:14] + "_SVO.mxf")); return did

def test_live_is_a_single_switch_and_dry_is_the_default():
    base = {"BLAZE_SHOW_IDS": "34427,34428"}
    assert bp.Cfg({**base, "BLAZE_ATTACH": "live"}).attach == "live"           # v9.7.5: no extra lock; QUICKTEST_ and BLAZE_LIVE_SHOW_IDS only narrow it
    with pytest.raises(SystemExit): bp.Cfg({**base, "BLAZE_LIVE_SHOW_IDS": "99999", "BLAZE_ATTACH": "live"})      # a live show that is not followed is still a typo
    assert bp.Cfg({"BLAZE_SHOW_IDS": "34427"}).attach == "dry"            # the default: nothing is ever sent

def test_live_sends_once_reads_back_and_marks_attached(env, tmp_path):
    s, f, p, e = live_env(tmp_path); did = ready_clip(s, f, p); p.cycle(); p.cycle(); p.cycle()
    assert len(posts(f)) == 1, "exactly one attach, however many passes"
    form = posts(f)[0]; assert (form["clipType"], form["mosObjectId"], form["order"], form["itemId"], form["showId"], form["duration"]) == ("MEDIA", "1103586", "15", "900001", "34427", "50")
    L = watch_lines(p); assert any("ATTACHING" in x and did in x for x in L) and any("ATTACHED" in x and "Blaze clip id" in x and 'story 724921 "AUTO ID 05"' in x for x in L)
    assert [r for r in clips(s) if r["display_id"] == did][0]["state"] == "ATTACHED"
    p2 = bp.Poller(p.c); p2.cycle(); assert len(posts(f)) == 1, "a restart must not send it again"

def test_live_media_mode_attaches_without_the_nas_watcher(env, tmp_path):
    """v9.8.1: BLAZE_ATTACH_WHEN=media (default): Blaze's media list is enough, the NAS watcher need not have set ON_NITRO (the Dummy test case: NITRO green, NAS not mounted)."""
    for st in ("WAITING_FOR_CLIP", "EXPORTING"):
        (tmp_path / st).mkdir(); s, f, p, e = live_env(tmp_path / st); did = ready_clip(s, f, p); set_state(s, did, st); p.cycle(); p.cycle()
        assert len(posts(f)) == 1, st
        assert [r for r in clips(s) if r["display_id"] == did][0]["state"] == "ATTACHED"

def test_live_waits_for_nitro_and_for_the_kill_switch(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_ATTACH_WHEN="watcher"); did = ready_clip(s, f, p); set_state(s, did, "EXPORTING"); p.cycle()      # watcher mode: the old rule, wait for the NAS watcher
    assert not posts(f)      # watcher mode plans only ON_NITRO clips, so an EXPORTING clip is simply not touched
    set_state(s, did, "ON_NITRO"); (tmp_path / "STOP_LIVE").write_text("stopped by hand"); p.cycle()
    assert not posts(f) and any("kill switch file" in x for x in watch_lines(p))
    (tmp_path / "STOP_LIVE").unlink(); p.cycle(); assert len(posts(f)) == 1

def test_live_sends_nothing_for_unverified_formats_linked_stories_or_other_shows(env, tmp_path):
    s, f, p, e = live_env(tmp_path); f.linked = {"21": [34500]}
    ready_clip(s, f, p, 20, "PKG X", 1, 23, 5); ready_clip(s, f, p, 21, "ANC Y", 2, 20, 6); p.cycle()
    assert [x["mosObjectId"] for x in posts(f)] == ["6"] and any("not yet verified for story format 23" in x and "NOT SENT" in x for x in watch_lines(p))      # v10.4.0: the linked (shared) story IS sent, once; only the unverified format waits
    assert not any("linked in shows" in x and "NOT SENT" in x for x in watch_lines(p))
    assert "BLAZE_LIVE_SHOW_IDS" in p.live_block({"blaze_rundown_id": "99999", "state": "ON_NITRO"}, [])

def test_refused_attach_goes_to_the_desk_and_is_never_repeated(env, tmp_path):
    s, f, p, e = live_env(tmp_path); f.post_mode = "refuse"; did = ready_clip(s, f, p); p.cycle(); p.cycle(); p.cycle()
    assert len(posts(f)) == 1 and any("ATTACH FAILED" in x and "story is locked" in x for x in watch_lines(p))
    row = [r for r in clips(s) if r["display_id"] == did][0]; assert row["state"] == "NEEDS_DESK"
    with s.app.db.tx() as cur: err = cur.one("SELECT f.error FROM files f JOIN clip_ids c ON c.id=f.clip_id WHERE c.display_id=? ORDER BY f.id DESC", (did,))["error"]
    assert "did not work" in err and "story is locked" in err     # the desk page shows this reason next to the clip
    assert p.led.live_of(did)["status"] == "FAILED"
    assert p.led.live_clear(did) == 1 and p.led.live_of(did) is None           # live-retry clears the record: one new attempt becomes possible

def test_attach_that_blaze_accepts_but_does_not_show_is_flagged_and_can_be_undone(env, tmp_path):
    s, f, p, e = live_env(tmp_path); f.post_mode = "noop"; did = ready_clip(s, f, p); p.cycle()
    assert len(posts(f)) == 1 and p.led.live_of(did)["status"] == "CHECK_FAILED" and [r for r in clips(s) if r["display_id"] == did][0]["state"] == "NEEDS_DESK"


def test_double_added_clip_is_caught_and_undo_removes_the_one_named(env, tmp_path):
    s, f, p, e = live_env(tmp_path); f.post_mode = "double"; did = ready_clip(s, f, p); p.cycle()
    row = p.led.live_of(did); assert row["status"] == "CHECK_FAILED" and len(row["blaze_clip_id"].split(",")) == 2 and "undo" in " ".join(watch_lines(p))
    assert "exactly one" in bp.undo(p.c, p.b, [did]); out = bp.undo(p.c, p.b, [did, row["blaze_clip_id"].split(",")[1]])
    assert "removed Blaze clip" in out and [x for x in f.log if x[0] == "DELETE"] and len(f.story_clips["724921"]) == 1 and p.led.live_of(did)["status"] == "UNDONE"

def test_undo_after_a_good_attach_removes_that_clip(env, tmp_path):
    s, f, p, e = live_env(tmp_path); did = ready_clip(s, f, p); p.cycle(); assert len(f.story_clips["724921"]) == 1
    assert "removed Blaze clip" in bp.undo(p.c, p.b, [did]) and f.story_clips["724921"] == [] and "no live attach is recorded" in bp.undo(p.c, p.b, ["20260101_0001A_NOPE"])

def test_three_failures_in_a_row_halt_live_and_the_next_clip_is_not_sent(env, tmp_path):
    s, f, p, e = live_env(tmp_path); f.post_mode = "refuse"
    for i in range(4): ready_clip(s, f, p, 100 + i, "S%d" % i, i + 1, 20, 500 + i)
    p.cycle(); assert len(posts(f)) == 3 and (tmp_path / "STOP_LIVE").exists() and any("LIVE HALTED" in x for x in watch_lines(p)), "stopped after the third failure, the fourth was not sent"

def test_hourly_limit_holds_back_the_extra_clips(env, tmp_path):
    s, f, p, e = live_env(tmp_path, BLAZE_LIVE_MAX_PER_HOUR="1")
    for i in range(2): ready_clip(s, f, p, 200 + i, "T%d" % i, i + 1, 20, 600 + i)
    p.cycle(); assert len(posts(f)) == 1 and any("hourly limit" in x for x in watch_lines(p))

def test_live_status_text_and_dry_mode_never_posts(env, tmp_path):
    s, f, p, e = live_env(tmp_path); did = ready_clip(s, f, p); p.cycle(); t = bp.live_status(p.c)
    assert "ON only shows 34427" in t and "SENT" in t and did in t and "kill switch file" in t
    s2 = bp.Cfg({**e, "BLAZE_ATTACH": "dry"}); assert "OFF (BLAZE_ATTACH=dry)" in bp.live_status(s2)
