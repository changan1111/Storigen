"""v10.17.0: one Add media per story; clips added by hand in Blaze on the dashboard; the chat sees the real clip list; the violence button and the Groq connection messages."""
import json, pathlib, socket, urllib.error
import pytest
from test_server import Srv

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
from autoid_lite.api_blazeclips import merge_blaze, parse_clip_name
from autoid_lite.api_bot import plan_names
from autoid_lite import clipsummary


def row(name, v=1, state="ATTACHED"): return {"name_id": name, "display_id": name, "version": v, "state": state, "replaced_at": None}


# ---------- 3) the name logic ----------
def test_a_hand_added_v01_makes_the_next_append_v02():
    base = "231126_FIRE"; rows, others = merge_blaze(base, [row(base)], [{"id": "1", "mos": "m1", "title": base}, {"id": "2", "mos": "m2", "title": base + "_V01"}])
    assert not others and plan_names(base, rows)["next_v"] == base + "_V02"
    assert plan_names(base, [row(base)])["next_v"] == base + "_V01", "without the Blaze list the bot said V01 again: the bug"

def test_hand_added_updates_and_chained_updates_are_placed():
    base = "231126_FIRE"; rows, others = merge_blaze(base, [row(base), row(base + "_V01", 2001)], [{"id": "3", "title": base + "_U01"}, {"id": "4", "title": base + "_V01_U01"}])
    p = plan_names(base, rows); assert not others and p["main"]["next_u_name"] == base + "_U02" and p["added"][0]["next_u_name"] == base + "_V01_U02" and p["next_v"] == base + "_V02"

def test_other_names_are_listed_apart_and_never_change_the_numbering():
    base = "231126_FIRE"; rows, others = merge_blaze(base, [row(base)], [{"id": "9", "title": "SOMETHING_ELSE"}, {"id": "8", "title": "231126_FIRE_FINAL"}, {"id": "7", "title": "231126_OTHER_V05"}])
    assert [o["name"] for o in others] == ["SOMETHING_ELSE", "231126_FIRE_FINAL", "231126_OTHER_V05"] and plan_names(base, rows)["next_v"] == base + "_V01"

def test_parse_clip_name():
    assert parse_clip_name("231126_FIRE") == ("231126_FIRE", 1) and parse_clip_name("231126_FIRE_V01.mxf") == ("231126_FIRE", 2001) and parse_clip_name("231126_FIRE_U03") == ("231126_FIRE", 1003)
    assert parse_clip_name("231126_FIRE_V01_U02") == ("231126_FIRE", 10102) and parse_clip_name("231126_FIRE_U01_V02") is None and parse_clip_name("231126_FIRE_V00") is None


# ---------- 2) the server keeps the full list; the dashboard shows hand-added clips ----------
def story(tmp_path, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("VERSION_SUFFIX", "on")
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    r = s.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO1", "blaze_story_id": "740371", "slug": "KARTHIK CLIP CHECK", "rundown_name": "21:30 Bulletin"})
    assert r[0] == 200, r
    with s.app.db.tx() as cur:
        cid = cur.q("SELECT c.id FROM clip_ids c JOIN stories st ON st.id=c.story_id WHERE st.blaze_story_id='740371' ORDER BY c.id")[0]["id"]
        cur.x("UPDATE clip_ids SET state='ATTACHED', media_id='1126526', blaze_clip_id='957411' WHERE id=?", (cid,))
    return s, cid

def test_the_server_keeps_the_list_and_ignores_a_repeat(tmp_path, monkeypatch):
    s, cid = story(tmp_path, monkeypatch); body = {"story": "740371", "clips": [{"id": "957411", "mos": "1126526", "title": "BASE", "dur_s": 23}, {"id": "957500", "mos": "1126999", "title": "231126_KARTHIK_V01", "dur_s": 9}]}
    assert s.svc("POST", "/svc/story_clips", body)[1]["changed"] is True and s.svc("POST", "/svc/story_clips", body)[1]["changed"] is False
    assert s.call("POST", "/svc/story_clips", body, key=False)[0] in (401, 403), "only the service key"
    assert s.svc("POST", "/svc/story_clips", {"story": "manual-x", "clips": []})[0] == 422 and s.svc("POST", "/svc/story_clips", {"story": "1", "clips": "no"})[0] == 422

def test_a_hand_added_clip_shows_as_a_card_with_delete_and_counts(tmp_path, monkeypatch):
    s, cid = story(tmp_path, monkeypatch)
    assert [x["role"] for x in s.call("GET", "/api/clips/%d/history" % cid)[1]["story_clips"]] == ["original"], "before: only what Storigen made"
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "957411", "mos": "1126526", "title": "BASE"}, {"id": "957500", "mos": "1126999", "title": "231126_KARTHIK_V01", "dur_s": 9}]})
    g = s.call("GET", "/api/clips/%d/history" % cid)[1]["story_clips"]
    assert [x["role"] for x in g] == ["original", "hand"] and g[1]["blaze_clip_id"] == "957500" and g[1]["state"] == "ATTACHED" and g[1]["by_hand"] and g[1]["name_id"] == "231126_KARTHIK_V01" and not g[1]["on_nitro"]
    c = [x for x in s.call("GET", "/api/clips")[1]["clips"] if x["id"] == cid][0]; assert c["story_clips"] == 2 and c["hand_clips"] == 1
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "957411", "mos": "1126526", "title": "BASE"}]})      # deleted again in Blaze: the card goes
    assert [x["role"] for x in s.call("GET", "/api/clips/%d/history" % cid)[1]["story_clips"]] == ["original"]


# ---------- 3) the chat: asks Blaze (through the poller), falls back, never waits for a poller that is not there ----------
def test_the_chat_merges_the_stored_list_when_the_poller_is_not_running(tmp_path, monkeypatch):
    s, cid = story(tmp_path, monkeypatch); base = s.call("GET", "/api/bot/story?rundown=RO1&story=740371")[1]
    assert base["blaze"]["source"] == "none" and base["next_v"].endswith("_V01")
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "957411", "mos": "1126526", "title": base["base"]}, {"id": "957500", "mos": "1", "title": base["base"] + "_V01"}, {"id": "5", "mos": "2", "title": "UNRELATED_NAME"}]})
    p = s.call("GET", "/api/bot/story?rundown=RO1&story=740371")[1]
    assert p["blaze"]["source"] == "poller" and "last saw" in p["blaze"]["note"] and p["next_v"] == base["base"] + "_V02" and [o["name"] for o in p["other_clips"]] == ["UNRELATED_NAME"]
    assert any(x["name"] == base["base"] + "_V01" for x in p["clips"])

def test_the_chat_asks_the_poller_for_a_fresh_list_when_it_is_running(tmp_path, monkeypatch):
    import threading, time
    s, cid = story(tmp_path, monkeypatch)
    with s.app.db.tx() as cur: cur.x("INSERT OR REPLACE INTO heartbeats(component, ts, detail) VALUES('blaze_poll', ?, '{}')", (time.time(),))
    def poller():                                                                                    # what blaze/support.py sup_list does, in miniature
        for _ in range(40):
            for j in s.svc("GET", "/svc/support/jobs?kind=LIST")[1]:
                s.svc("POST", "/svc/support/result", {"id": j["id"], "state": "DONE", "message": "2 clip(s)", "result": {"clips": [{"id": "957411", "mos": "1126526", "title": "X"}, {"id": "957500", "mos": "7", "title": "HAND_V01"}], "shows": ["RO1"], "show_names": ["B"], "story_title": "T"}}); return
            time.sleep(0.1)
    t = threading.Thread(target=poller); t.start(); p = s.call("GET", "/api/bot/story?rundown=RO1&story=740371")[1]; t.join()
    assert p["blaze"]["source"] == "blaze" and p["blaze"]["count"] == 2
    with s.app.db.tx() as cur: assert [x["kind"] for x in cur.q("SELECT kind FROM support_jobs")] == ["LIST"], "only the read-only request"


# ---------- the poller reports every read ----------
def test_the_poller_reports_the_full_list_once_until_it_changes():
    from autoid_lite.blaze.clipreport import ClipReportMixin
    class P(ClipReportMixin):
        def __init__(self): self.sent = []; self.a = self; self.b = self
        def call(self, path, body=None): self.sent.append((path, body))
        def story_info(self, sid): return {"rows": [{"id": "1", "mos": "m", "title": "T", "dur": 5000}]}
        def rt(self, fn): return fn()
    p = P(); p.sup_read("77"); p.sup_read("77"); assert len(p.sent) == 1 and p.sent[0][0] == "/svc/story_clips" and p.sent[0][1] == {"story": "77", "clips": [{"id": "1", "mos": "m", "title": "T", "dur_s": 5}]}
    p.b.story_info = lambda sid: {"rows": []}; p.sup_read("77"); assert len(p.sent) == 2, "a clip deleted in Blaze is reported"
    p.report_clips("77", {"partial": True, "rows": []}, force=True); assert len(p.sent) == 2, "a partial read is never reported"


# ---------- 1) the page ----------
def test_one_add_media_per_story_delete_on_each_clip_and_hand_cards():
    g = PAGE[PAGE.index("function gallery("):PAGE.index("function startPreview(")]
    assert g.count("addBtn(c)") == 1 and "delBtn(x,c)" in g and "Added by hand" in g and "No quality checks" in g
    assert "Violence check (AI)" in PAGE and "An admin turns it on in Users > Features > AI standards check" in PAGE
    assert "Other clips in this story" in PAGE and "Checked against Blaze just now" in PAGE

# ---------- 4) Groq ----------
def test_groq_unreachable_says_why(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_123456")
    for err, word in ((socket.gaierror(-2, "Name or service not known"), "name api.groq.com could not be found"), (socket.timeout("timed out"), "no answer in time"), (ConnectionRefusedError(), "refused")):
        def op(req, timeout=0, e=err): raise urllib.error.URLError(e)
        with pytest.raises(Exception) as ei: clipsummary.post_groq({"x": 1}, opener=op)
        assert word in str(ei.value.args[0] if ei.value.args else ei.value) or word in getattr(ei.value, "message", str(ei.value)); assert "gsk_test_key" not in str(ei.value) and "firewall" in str(ei.value) + getattr(ei.value, "message", "")

def test_groq_proxy_setting_is_used(monkeypatch):
    monkeypatch.setenv("GROQ_PROXY", "http://proxy.local:3128"); h = [x for x in clipsummary._opener().handlers if x.__class__.__name__ == "ProxyHandler"][0]
    assert h.proxies["https"] == "http://proxy.local:3128"
