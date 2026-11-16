"""24/7 behaviour of the server: quiet polls leave no events, the audit table stays append-only, components can raise an alert."""
import pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "tests"))
from test_server import Srv

def events(s, action=None):
    q, a = ("SELECT COUNT(*) AS n FROM events WHERE action=?", (action,)) if action else ("SELECT COUNT(*) AS n FROM events", ())
    return s.app.db.conn.execute(q, a).fetchone()["n"]

def stories(n): return [{"blaze_story_id": str(724000 + i), "slug": "STORY %d" % i, "slug_id": str(i), "position": i} for i in range(n)]

def test_polling_an_unchanged_rundown_writes_no_event_but_a_real_change_does(tmp_path):
    s = Srv(tmp_path, "story_id"); sync = lambda st: s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "34498", "rundown_name": "A", "stories": st})
    assert sync(stories(5))[0] == 200 and events(s, "rundown_synced") == 1                  # first sight: 5 stories created
    for _ in range(50): assert sync(stories(5))[0] == 200
    assert events(s, "rundown_synced") == 1, "50 quiet polls must add nothing (was one row per poll)"
    sync(stories(6)); assert events(s, "rundown_synced") == 2                                # a story was added
    sync(stories(4)); assert events(s, "rundown_synced") == 3                                # two were removed

def test_the_audit_table_stays_append_only(tmp_path):
    import sqlite3, pytest
    s = Srv(tmp_path, "story_id"); s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "1", "rundown_name": "A", "stories": stories(2)})
    with pytest.raises(sqlite3.IntegrityError): s.app.db.conn.execute("DELETE FROM events")
    with pytest.raises(sqlite3.IntegrityError): s.app.db.conn.execute("UPDATE events SET action='x'")

def test_a_component_can_ask_for_an_alert(tmp_path, monkeypatch):
    from autoid_lite import server
    sent = []; monkeypatch.setattr(server, "send_alert", lambda text: sent.append(text))
    s = Srv(tmp_path, "story_id"); code, body = s.svc("POST", "/svc/alert", {"text": "Blaze session expired"})
    import time; time.sleep(0.2)
    assert code == 200 and body == {"ok": True} and sent == ["Blaze session expired"] and events(s, "alert") == 1
    assert s.svc("POST", "/svc/alert", {})[0] != 200                       # text is required
    assert s.call("POST", "/svc/alert", {"text": "x"}, key=False, cookie=False)[0] in (401, 403)      # needs the service key
