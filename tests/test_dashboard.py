"""The story-tracker page's data (clip history), the tool-vs-desk report page (HTML written by the poller, served by the web app), and that nothing from Blaze can inject markup."""
import os as _os; _os.environ.setdefault("ID_FORMAT", "legacy")      # these tests pin the legacy YYYYMMDD_NNNNC_ ID; test_clip_names_and_versions.py covers DDMMYY_STORY_NAME
import pathlib, sys, urllib.error, urllib.request
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "tools")); sys.path.insert(0, str(root))
import blaze_ledger as bl
from test_server import Srv
from test_blaze_poll import env, slug, media, clips as clips_of, set_state       # noqa: F401  (env is a fixture)

def fetch(s, path, cookie=True):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (s.port, path), headers={"Cookie": s.cookie} if cookie and s.cookie else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return r.status, r.read().decode("utf-8"), r.headers.get("Content-Type")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8"), e.headers.get("Content-Type")

@pytest.fixture
def web(tmp_path):
    s = Srv(tmp_path, "story_id", {"BLAZE_REPORT_DIR": str(tmp_path / "reports")}); assert s.login()[0] == 200; (tmp_path / "reports").mkdir(); s.reports = tmp_path / "reports"; return s

def make(s, story="726521", title="EXP VNR AGRI", pos=148):
    return s.svc("POST", "/svc/stories", {"blaze_rundown_id": "34498", "blaze_story_id": story, "slug": title, "rundown_name": "9 PM Bulletin", "position": pos})[1]

def test_clip_history_follows_the_clip_from_story_to_attachment(web):
    c = make(web); did = c["display_id"]; cid = web.call("GET", "/api/clips")[1]["clips"][0]["id"]
    h = web.call("GET", "/api/clips/%d/history" % cid)[1]; assert [s["key"] for s in h["steps"]] == ["story", "id", "export", "nitro", "attach"]
    assert [s["done"] for s in h["steps"]] == [True, True, False, False, False] and "row 148" in h["steps"][0]["detail"] and h["file"] is None
    web.svc("POST", "/svc/files", {"display_id": did, "state": "EXPORTING", "nas_path": "\\\\nas\\Playout\\INBOX\\%s.mxf" % did})
    web.svc("POST", "/svc/files", {"display_id": did, "state": "ON_NITRO", "nitro_path": "/Volumes/Nitro/%s.mxf" % did, "duration_s": 50.4, "size": 99})
    h = web.call("GET", "/api/clips/%d/history" % cid)[1]; assert [s["done"] for s in h["steps"]] == [True, True, True, True, False]
    assert did + ".mxf" in h["steps"][2]["detail"] and h["file"] == {"name": did + ".mxf", "where": "Nitro", "size": 99, "duration_s": 50.4}
    web.svc("POST", "/svc/attach/confirm", {"display_id": did, "blaze_rundown_id": "34498", "blaze_story_id": "726521"})
    h = web.call("GET", "/api/clips/%d/history" % cid)[1]; assert h["state"] == "ATTACHED" and h["steps"][4]["done"] and h["steps"][4]["label"] == "Attachment verified"

def test_clip_history_shows_the_problem_and_needs_a_login(web):
    c = make(web); did = c["display_id"]; cid = web.call("GET", "/api/clips")[1]["clips"][0]["id"]
    web.svc("POST", "/svc/files", {"display_id": did, "state": "NEEDS_DESK", "error": "checksum mismatch"})
    h = web.call("GET", "/api/clips/%d/history" % cid)[1]; assert h["steps"][-1] == {**h["steps"][-1], "key": "problem", "problem": True, "detail": "checksum mismatch"}
    assert web.call("GET", "/api/clips/99999/history")[0] == 404
    web.cookie = None; assert web.call("GET", "/api/clips/%d/history" % cid)[0] == 401

def test_report_page_needs_the_dashboard_login_and_serves_only_report_files(web):
    (web.reports / "agreement_20261107.html").write_text("<h1>MARKER</h1>", encoding="utf-8"); (web.reports / "agreement_20261107.csv").write_text("secret,csv", encoding="utf-8")
    st, body, ct = fetch(web, "/report/20261107", cookie=False); assert st == 401 and "Sign in first" in body and "MARKER" not in body
    st, body, ct = fetch(web, "/report/20261107"); assert st == 200 and "MARKER" in body and ct.startswith("text/html")
    for bad in ("/report/20261108", "/report/abc", "/report/20261107.csv", "/report/..%2F..%2Fautoid.db", "/report/../t.db", "/report/2026110"): assert fetch(web, bad)[0] == 404, bad
    st, body, _ = fetch(web, "/report"); assert st == 404 and "No report for" in body            # today's page does not exist yet: a clear message, not a crash

def results(**kw):
    o = {"display_id": "20261107_0001N_X", "show": "34498", "slug_id": "1", "row": 148, "story": "726521", "title": "EXP VNR", "status": "AGREE", "detail": "", "tool_media": "1", "tool_file": "x.mxf",
         "tool_planned_at": "14:02:11", "desk_media": "1", "desk_first_seen": "14:06:40"}; o.update(kw); return o

def summ(res):
    c = {k: sum(1 for o in res if o["status"] == k) for k in bl.ORDER}; d = sum(c[k] for k in bl.DECIDED); return {"counts": c, "decided": d, "rate": c["AGREE"] / d if d else None}

def test_report_html_escapes_everything_that_comes_from_blaze():
    evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    res = [results(title=evil, status="DISAGREE", detail="media <b>1</b> " + evil, display_id="20261107_0002P_" + evil, story=evil, tool_file=evil, desk_media=evil)]
    page = bl.render_html("2026-11-07", res, summ(res), {"34498": evil}, [{"day": evil, "clips": 1, "rate": 0.5, "decided": 2, "counts": summ(res)["counts"]}], "dry", evil, {"prev": "20261106", "next": None})
    assert "<script>alert" not in page and "<img src=x" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert page.count("<script>") == 1, "only our own filter script"

def test_report_html_has_the_counts_the_code_computes():
    res = [results(), results(display_id="B", status="DISAGREE", detail="d"), results(display_id="C", status="OVERDUE"), results(display_id="D", status="NO_FILE", tool_media="", desk_media="")]
    page = bl.render_html("2026-11-07", res, summ(res), {"34498": "9 PM Bulletin"}, None, "dry", "now")
    assert "50%" in page and "1 of 2 attached clips" in page and "9 PM Bulletin" in page and "DRY RUN" in page and "Needs a look 2" in page and "no file found yet" in page
    assert "LIVE ATTACH ON" in bl.render_html("d", res, summ(res), {}, None, "live", "now") and "no longer measures" in bl.render_html("d", res, summ(res), {}, None, "live", "now")

def test_the_poller_writes_today_s_html_report_without_touching_the_csv(env):
    s, f, p = env; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); did = clips_of(s)[0]["display_id"]; day = p.server_day().strftime("%Y%m%d"); rp = pathlib.Path(p.c.reports)
    p.write_page(); html = (rp / ("agreement_%s.html" % day)).read_text(encoding="utf-8")
    assert did in html and "AUTO ID 05" in html and "Row 14" in html and "05_11_14:30 PM Bulletin" in html and not list(rp.glob("agreement_*.csv")) and not list(rp.glob("*.tmp"))
    txt = p.report(); assert (rp / ("agreement_%s.csv" % day)).exists() and "Tool vs desk" in txt
    (rp / "agreement_20260101.html").write_text("old", encoding="utf-8"); p.report(); assert "/report/20260101" in (rp / ("agreement_%s.html" % day)).read_text(encoding="utf-8")      # link to the earlier day

def test_a_failing_report_write_never_stops_polling(env, monkeypatch):
    s, f, p = env; f.slugs = [slug(1, "A", 1)]
    def boom(*a, **k): raise OSError("disk full")
    monkeypatch.setattr(p, "report", boom); p.write_page(); p.write_page(); assert p.page_err == "disk full"; p.cycle()


# ================= paging a 700-story day =================
def many(web, n=120, shows=(100, 101, 102)):
    ids = []
    for i in range(n):
        c = web.svc("POST", "/svc/stories", {"blaze_rundown_id": str(shows[i % len(shows)]), "blaze_story_id": str(800000 + i), "slug": "STORY %03d%s" % (i, " 50%_OFF" if i == 7 else ""), "rundown_name": "Show %d" % shows[i % len(shows)], "position": i // len(shows) + 1})[1]
        ids.append(c["display_id"])
    return ids

def test_clip_list_is_paged_and_counts_cover_the_whole_day(web):
    ids = many(web)
    d = web.call("GET", "/api/clips?per_page=50&page=1")[1]; assert len(d["clips"]) == 50 and d["total"] == 120 and d["pages"] == 3 and d["page"] == 1 and d["counts"]["all"] == 120
    assert len(web.call("GET", "/api/clips?per_page=50&page=3")[1]["clips"]) == 20 and web.call("GET", "/api/clips?per_page=50&page=99")[1]["page"] == 3, "a page past the end is moved back to the last page"
    seen = [c["display_id"] for p in (1, 2, 3) for c in web.call("GET", "/api/clips?per_page=50&page=%d" % p)[1]["clips"]]; assert sorted(seen) == sorted(ids) and len(set(seen)) == 120, "every clip on exactly one page"
    assert len(web.call("GET", "/api/clips")[1]["clips"]) == 120, "without paging parameters: everything, as before"
    assert len(web.call("GET", "/api/clips?per_page=1000")[1]["clips"]) == 120, "the page size is capped at 200"
    assert [s["id"] for s in d["shows"]] == ["100", "101", "102"] and {s["n"] for s in d["shows"]} == {40}

def test_filters_search_and_show_work_with_paging_and_put_action_first(web):
    ids = many(web)
    for did in ids[5:15]: web.svc("POST", "/svc/files", {"display_id": did, "state": "ON_NITRO", "nitro_path": "/n/%s.mxf" % did})
    for did in ids[20:25]: web.svc("POST", "/svc/files", {"display_id": did, "state": "NEEDS_DESK", "error": "x"})
    web.svc("POST", "/svc/files", {"display_id": ids[30], "state": "ON_NITRO", "nitro_path": "/n/x.mxf"})
    web.svc("POST", "/svc/attach/confirm", {"display_id": ids[30], "blaze_rundown_id": "100", "blaze_story_id": "800030"})
    d = web.call("GET", "/api/clips?per_page=20&page=1")[1]; assert [c["state"] for c in d["clips"][:15]] == [c["state"] for c in sorted(d["clips"][:15], key=lambda c: 0)] and all(c["state"] in ("ON_NITRO", "NEEDS_DESK") for c in d["clips"][:15]), "needing action first"
    c = d["counts"]; assert (c["on_nitro"], c["needs_desk"], c["attached"], c["action"], c["done"], c["waiting"], c["all"]) == (10, 5, 1, 15, 1, 104, 120)
    a = web.call("GET", "/api/clips?filter=action&per_page=10&page=2")[1]; assert a["total"] == 15 and len(a["clips"]) == 5 and a["pages"] == 2 and all(x["state"] in ("ON_NITRO", "NEEDS_DESK") for x in a["clips"])
    assert web.call("GET", "/api/clips?filter=done&per_page=50")[1]["total"] == 1 and web.call("GET", "/api/clips?filter=waiting&per_page=50")[1]["total"] == 104
    sh = web.call("GET", "/api/clips?show=101&per_page=50")[1]; assert sh["total"] == 40 and {x["blaze_rundown_id"] for x in sh["clips"]} == {"101"} and sh["counts"]["all"] == 40
    q = web.call("GET", "/api/clips?q=story%20042&per_page=50")[1]; assert q["total"] == 2 and {x["slug"] for x in q["clips"]} == {"STORY 042", "STORY 041"}, "every word must match somewhere (STORY 041's clip ID holds 0042)"
    assert web.call("GET", "/api/clips?q=story%20042%20800042&per_page=50")[1]["total"] == 1
    assert web.call("GET", "/api/clips?q=800099&per_page=50")[1]["total"] == 1 and web.call("GET", "/api/clips?q=%s&per_page=50" % ids[3].lower())[1]["total"] == 1
    assert web.call("GET", "/api/clips?q=50%25_off&per_page=50")[1]["total"] == 1 and web.call("GET", "/api/clips?q=%25&per_page=50")[1]["total"] == 1, "% and _ in the search are literal, not wildcards"
    assert web.call("GET", "/api/clips?q=nothing+like+it&per_page=50")[1]["clips"] == [] and web.call("GET", "/api/clips?q=nothing+like+it&per_page=50")[1]["pages"] == 1

def test_paging_rejects_bad_parameters(web):
    many(web, 3)
    assert web.call("GET", "/api/clips?per_page=x")[0] == 400 and web.call("GET", "/api/clips?filter=bogus")[0] == 400 and web.call("GET", "/api/clips?page=0&per_page=2")[1]["page"] == 1
    web.cookie = None; assert web.call("GET", "/api/clips?per_page=2")[0] == 401

def test_history_carries_the_clip_so_the_detail_panel_works_from_any_page(web):
    many(web, 3); cid = web.call("GET", "/api/clips?per_page=50")[1]["clips"][0]["id"]; h = web.call("GET", "/api/clips/%d/history" % cid)[1]
    assert h["clip"]["slug"].startswith("STORY") and h["clip"]["blaze_rundown_id"] == "100" and h["clip"]["position"] == 1 and h["clip"]["blaze_story_id"] == "800000"
