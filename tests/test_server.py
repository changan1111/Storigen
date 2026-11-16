"""The lite server over real HTTP: logins, both link modes, the service API used by the watcher and the MOS gateway, and the safety rules."""
import os as _os; _os.environ.setdefault("ID_FORMAT", "legacy")      # these tests pin the legacy YYYYMMDD_NNNNC_ ID; test_clip_names_and_versions.py covers DDMMYY_STORY_NAME
import datetime as dt, json, pathlib, sys, threading, urllib.error, urllib.request
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root))
from autoid_lite import server

KEY, SECRET = "k" * 20, "s" * 40
ENV = {"SERVICE_API_KEY": KEY, "SESSION_SECRET": SECRET, "AUTOID_TZ": "", "HEALTH_COMPONENTS": "watcher"}

class Srv:
    def __init__(self, tmp, mode, extra=None):
        self.app = server.App(server.settings_from_env({**ENV, "LINK_MODE": mode, **(extra or {})}), tmp / "t.db")
        self.app.bootstrap_admin({"ADMIN_EMAIL": "admin@x.io", "ADMIN_PASSWORD": "adminpass1"})
        self.httpd = server.serve(self.app, "127.0.0.1", 0); self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start(); self.cookie = None
    def call(self, method, path, body=None, key=False, cookie=True, ctype="application/json"):
        h = {"Content-Type": ctype}
        if key: h["X-API-Key"] = KEY
        if cookie and self.cookie: h["Cookie"] = self.cookie
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                sc = r.headers.get("Set-Cookie")
                if sc and "sid=" in sc: self.cookie = sc.split(";")[0] if not sc.startswith("sid=;") else None
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"null")
    def login(self, email="admin@x.io", pw="adminpass1"): self.cookie = None; return self.call("POST", "/api/login", {"email": email, "password": pw})
    def svc(self, method, path, body=None): return self.call(method, path, body, key=True, cookie=False)

@pytest.fixture
def ph(tmp_path):
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; return s
@pytest.fixture
def sid(tmp_path):
    s = Srv(tmp_path, "story_id"); assert s.login()[0] == 200; return s

def clips(s): return s.call("GET", "/api/clips")[1]["clips"]

def test_placeholder_mode_makes_an_id_from_rundown_and_story_name(ph):
    st, c = ph.call("POST", "/api/manual", {"rundown": "03_11 9 PM Bulletin", "story": "HL Vijaya CHN Vidhyarambam 9AM"})
    today = ph.app.today().strftime("%Y%m%d")
    assert st == 200 and c["display_id"].startswith(today + "_0001") and c["display_id"].endswith("_HL_VIJAYA_CHN_VIDHYARAMBAM_9AM")
    row = clips(ph)[0]; assert row["rundown"] == "03_11 9 PM Bulletin" and row["slug"] == "HL Vijaya CHN Vidhyarambam 9AM" and row["typed"] is True

def test_placeholder_mode_needs_both_names_and_warns_about_duplicates(ph):
    assert ph.call("POST", "/api/manual", {"story": "A"})[0] == 400                                   # rundown missing
    assert ph.call("POST", "/api/manual", {"rundown": "R1", "story": "  "})[0] == 400                  # story missing
    first = ph.call("POST", "/api/manual", {"rundown": "R1", "story": "Big Fire"})[1]["display_id"]
    st, e = ph.call("POST", "/api/manual", {"rundown": " r1 ", "story": "big   FIRE"})                 # same names, different case and spacing
    assert st == 409 and e["duplicate"] == first
    assert ph.call("POST", "/api/manual", {"rundown": "R2", "story": "Big Fire"})[0] == 200           # other rundown: fine
    st, c = ph.call("POST", "/api/manual", {"rundown": "R1", "story": "Big Fire", "confirm_duplicate": True})
    assert st == 200 and c["display_id"] != first and c["display_id"].split("_")[1].startswith("0003")

def test_rundown_names_are_offered_for_autocomplete(ph):
    ph.call("POST", "/api/manual", {"rundown": "Morning Show", "story": "x"}); ph.call("POST", "/api/manual", {"rundown": "9 PM Bulletin", "story": "y"})
    assert ph.call("GET", "/api/rundowns")[1] == ["9 PM Bulletin", "Morning Show"]

def test_story_id_mode_makes_ids_from_the_feed_and_turns_typing_off(sid):
    st, e = sid.call("POST", "/api/manual", {"rundown": "R", "story": "S"}); assert st == 409 and "LINK_MODE=story_id" in e["detail"]
    assert sid.call("GET", "/api/config")[1]["manual_enabled"] is False
    a = sid.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO1", "blaze_story_id": "ST1", "slug": "Fire in town", "rundown_name": "9 PM"})[1]
    b = sid.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO1", "blaze_story_id": "ST1", "slug": "Fire in town (edited)"})[1]
    assert a["display_id"] == b["display_id"] and len(clips(sid)) == 1                                     # same story, same ID, no duplicate
    assert sid.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO1", "blaze_story_id": "ST2", "slug": "Other"})[1]["seq"] == 2
    row = clips(sid)[0]; assert row["blaze_story_id"] == "ST1" and row["rundown"] == "9 PM" and row["typed"] is False

def test_story_id_mode_can_allow_typing_as_a_fallback(tmp_path):
    s = Srv(tmp_path, "story_id", {"ALLOW_MANUAL": "1"}); s.login(); assert s.call("POST", "/api/manual", {"story": "Only a name"})[0] == 200

def test_whole_rundown_sync_removes_missing_stories_and_holds_clips_on_nitro(sid):
    for n in ("A", "B", "C"): sid.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO", "blaze_story_id": n, "slug": "story " + n})
    ids = {c["blaze_story_id"]: c["display_id"] for c in clips(sid)}
    for n in ("B", "C"): assert sid.svc("POST", "/svc/files", {"display_id": ids[n], "state": "ON_NITRO"})[0] == 200
    r = sid.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "RO", "stories": [{"blaze_story_id": "A", "slug": "story A"}, {"blaze_story_id": "C", "slug": "story C"}]})[1]
    assert r["removed"] == 1 and r["held"] == [ids["B"]] and r["created"] == 0
    by = {c["blaze_story_id"]: c for c in clips(sid)}
    assert by["B"]["state"] == "NEEDS_DESK" and by["B"]["deleted"] and "STORY REMOVED" in by["B"]["error"] and by["C"]["state"] == "ON_NITRO"
    sid.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO", "blaze_story_id": "B", "slug": "story B"})              # the story is back
    b = {c["blaze_story_id"]: c for c in clips(sid)}["B"]; assert b["state"] == "NEEDS_DESK" and not b["deleted"] and "reappeared" in b["error"]

def test_story_delete_and_rename_and_confirm(sid):
    d = sid.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO", "blaze_story_id": "A", "slug": "a"})[1]["display_id"]
    sid.svc("POST", "/svc/files", {"display_id": d, "state": "ON_NITRO"})
    assert sid.svc("POST", "/svc/stories/rename", {"blaze_rundown_id": "RO", "old_id": "A", "new_id": "A2"})[1]["updated"] == 1
    assert sid.svc("POST", "/svc/attach/confirm", {"display_id": d, "blaze_rundown_id": "RO", "blaze_story_id": "OTHER"})[1]["state"] == "NEEDS_DESK"      # wrong story
    assert sid.svc("POST", "/svc/files", {"display_id": d, "state": "ON_NITRO"})[0] == 200
    assert sid.svc("POST", "/svc/attach/confirm", {"display_id": d, "blaze_rundown_id": "RO", "blaze_story_id": "A2"})[1]["state"] == "ATTACHED"
    assert sid.svc("POST", "/svc/stories/delete", {"blaze_rundown_id": "RO", "blaze_story_id": "A2"})[1]["held"] == []                                   # ATTACHED history is never touched
    assert clips(sid)[0]["state"] == "ATTACHED"

def test_watcher_flow_match_with_check_letter_and_states(ph):
    did = ph.call("POST", "/api/manual", {"rundown": "R", "story": "Fire"})[1]["display_id"]; day, num, _ = did.split("_", 2); seq, chk = int(num[:4]), num[4:]
    assert ph.svc("GET", "/svc/match?day=%s&seq=%d&version=1&chk=%s" % (day, seq, chk))[1]["display_id"] == did
    assert ph.svc("GET", "/svc/match?day=%s&seq=%d&version=1&chk=%s" % (day, seq, "A" if chk != "A" else "C"))[0] == 422               # mistyped check letter
    assert ph.svc("GET", "/svc/match?day=%s&seq=999&version=1" % day)[0] == 404
    for state in ("EXPORTING", "ON_NITRO"): assert ph.svc("POST", "/svc/files", {"display_id": did, "state": state, "nas_path": "/p/x.mov"})[0] == 200
    assert clips(ph)[0]["state"] == "ON_NITRO"
    assert ph.svc("POST", "/svc/files", {"display_id": did, "state": "NOPE"})[0] == 400 and ph.svc("POST", "/svc/files", {"display_id": "x_y", "state": "ON_NITRO"})[0] == 404
    cid = clips(ph)[0]["id"]; assert ph.call("POST", "/api/clips/%d/attached" % cid)[0] == 200 and clips(ph)[0]["state"] == "ATTACHED"
    assert ph.call("POST", "/api/clips/%d/attached" % cid)[0] == 409                                                                    # not twice
    assert ph.svc("POST", "/svc/files", {"display_id": did, "state": "EXPORTING"})[0] == 200 and clips(ph)[0]["state"] == "ATTACHED"    # a late event never undoes ATTACHED

def test_versions_get_their_own_id(ph):
    c = ph.call("POST", "/api/manual", {"rundown": "R", "story": "Fire"})[1]; v = ph.call("POST", "/api/clips/%d/version" % c["id"])[1]
    assert v["display_id"] == c["display_id"] + "_V2" and v["seq"] == c["seq"] and v["version"] == 2

def test_service_endpoints_need_the_api_key_and_ui_endpoints_need_a_login(ph):
    assert ph.call("GET", "/svc/status", key=False, cookie=False)[0] == 401
    ph.call("POST", "/api/logout"); assert ph.call("GET", "/api/clips")[0] == 401 and ph.call("GET", "/api/me")[0] == 401
    assert ph.call("POST", "/api/manual", {"rundown": "R", "story": "x"}, ctype="text/plain")[0] in (401, 415)

def test_form_posts_without_json_are_refused(ph):
    assert ph.call("POST", "/api/manual", {"rundown": "R", "story": "x"}, ctype="application/x-www-form-urlencoded")[0] == 415

def test_tampered_or_expired_session_is_refused(ph):
    good = ph.cookie; ph.cookie = good[:-3] + ("aaa" if not good.endswith("aaa") else "bbb"); assert ph.call("GET", "/api/me")[0] == 401
    ph.cookie = None; from autoid_lite.security import make_token
    uid = ph.app.db.conn.execute("SELECT id FROM users").fetchone()["id"]
    ph.cookie = "sid=" + make_token(uid, SECRET, -10); assert ph.call("GET", "/api/me")[0] == 401
    ph.cookie = "sid=" + make_token(uid, "x" * 40, 100); assert ph.call("GET", "/api/me")[0] == 401                                      # signed with another secret

def test_wrong_password_is_throttled(tmp_path):
    s = Srv(tmp_path, "placeholder")
    for _ in range(5): assert s.login(pw="nope")[0] == 401
    assert s.login()[0] == 429

def test_user_rules_valid_upto_and_last_admin(ph):
    st, u = ph.call("POST", "/api/users", {"email": "ed@x.io", "password": "editorpass", "role": "editor", "valid_upto": "2999-01-01"}); assert st == 200 and u["valid"]
    assert ph.call("POST", "/api/users", {"email": "bad", "password": "editorpass", "role": "editor", "valid_upto": "2999-01-01"})[0] == 400
    assert ph.call("POST", "/api/users", {"email": "n@x.io", "password": "editorpass", "role": "editor"})[0] == 400                      # valid-upto is required
    assert ph.call("POST", "/api/users", {"email": "ED@x.io", "password": "editorpass", "role": "editor", "valid_upto": "2999-01-01"})[0] == 409
    me = ph.call("GET", "/api/me")[1]["id"]; assert ph.call("PATCH", "/api/users/" + me, {"role": "editor"})[0] == 409                    # cannot demote yourself / last admin
    old = (dt.date.today() - dt.timedelta(days=1)).isoformat(); assert ph.call("PATCH", "/api/users/" + u["id"], {"valid_upto": old})[0] == 200
    ed = Srv.__new__(Srv); ed.__dict__.update(ph.__dict__); ed.cookie = None; st, e = ed.login("ed@x.io", "editorpass")
    assert st == 403 and "contact the admin" in e["detail"]
    assert ph.call("PATCH", "/api/users/" + u["id"], {"valid_upto": "2999-01-01", "active": False})[0] == 200; assert ed.login("ed@x.io", "editorpass")[0] == 403
    assert ph.call("POST", "/api/users/%s/password" % u["id"], {"password": "short"})[0] == 400

def test_editor_cannot_manage_users(ph):
    ph.call("POST", "/api/users", {"email": "ed@x.io", "password": "editorpass", "role": "editor", "valid_upto": "2999-01-01"})
    ph.login("ed@x.io", "editorpass"); assert ph.call("GET", "/api/users")[0] == 403 and ph.call("GET", "/api/clips")[0] == 200

def test_events_are_append_only_and_listed_for_the_desk(ph):
    ph.call("POST", "/api/manual", {"rundown": "R", "story": "Fire"}); ev = ph.call("GET", "/api/events?limit=5")[1]
    assert any(e["action"] == "manual_clip_id" for e in ev) and isinstance(ev[0]["details"], dict)
    with pytest.raises(Exception):
        with ph.app.db.tx() as cur: cur.x("DELETE FROM events")

def test_health_reports_missing_and_stale_components(ph):
    assert ph.call("GET", "/api/status")[1]["problems"] == ["watcher has never reported"]
    ph.svc("POST", "/svc/heartbeat", {"component": "watcher", "detail": {"nas_ok": True}}); assert ph.call("GET", "/api/status")[1]["problems"] == []
    ph.svc("POST", "/svc/heartbeat", {"component": "watcher", "detail": {"nas_ok": False, "problem": "Nitro folder is missing"}}); assert ph.call("GET", "/api/status")[1]["problems"] == ["Nitro folder is missing"]

def test_backup_is_a_consistent_copy(ph, tmp_path):
    ph.call("POST", "/api/manual", {"rundown": "R", "story": "Fire"}); ph.app.db.backup(tmp_path / "b.db")
    import sqlite3; assert sqlite3.connect(str(tmp_path / "b.db")).execute("SELECT count(*) FROM clip_ids").fetchone()[0] == 1
