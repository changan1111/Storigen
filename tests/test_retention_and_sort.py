"""v10.9.4: AUTOID_KEEP_DAYS (default 7) clean-up of autoid.db and the poller's file; sort by # / title / status; the Removed filter and the hide-removed switch; the page's new controls."""
import sys, pathlib, datetime as dt, time, sqlite3, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from test_server import Srv, ENV, server
from autoid_lite.blaze.ledger import Ledger
from test_blaze_poll import bp

@pytest.fixture
def s(tmp_path):
    x = Srv(tmp_path, "story_id"); assert x.login()[0] == 200; x.tmp = tmp_path; return x
def sync(s, rid, rows, name="Bulletin"):
    st = [{"blaze_story_id": str(i), "slug": sl, "slug_id": str(900 + int(i)), "position": pos, "story_title": tt} for i, sl, pos, tt in rows]
    r = s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": rid, "rundown_name": name, "stories": st}); assert r[0] == 200, r; return r[1]
def sql(s, q, a=()):
    with s.app.db.tx() as cur: return cur.q(q, a)
def run(s, q, a=()):
    with s.app.db.tx() as cur: return cur.x(q, a)
def lst(s, **q):
    qs = "&".join("%s=%s" % kv for kv in {"per_page": 50, **q}.items()); st, b = s.call("GET", "/api/clips?" + qs); assert st == 200, b; return b
def slugs(b): return [c["slug"] for c in b["clips"]]
def clip_of(s, slug): return sql(s, "SELECT c.id FROM clip_ids c JOIN stories st ON st.id=c.story_id WHERE st.slug=?", (slug,))[0]["id"]
def cnt(s, t): return sql(s, "SELECT COUNT(*) n FROM %s" % t)[0]["n"]

# ------------------------------------------------------------------ settings
def test_the_keep_days_setting_defaults_to_7_and_is_checked():
    cfg = lambda **e: server.settings_from_env({**ENV, "LINK_MODE": "story_id", **e})
    assert cfg()["keep_days"] == 7 and cfg()["purge_at"] == "03:30"
    assert cfg(AUTOID_KEEP_DAYS="30", AUTOID_PURGE_AT="01:15")["keep_days"] == 30 and cfg(AUTOID_KEEP_DAYS="0")["keep_days"] == 0
    for bad in ("x", "-1", "3651", "7.5"):
        with pytest.raises(SystemExit): cfg(AUTOID_KEEP_DAYS=bad)
    for bad in ("25:00", "3:30", "0330", "ab"):
        with pytest.raises(SystemExit): cfg(AUTOID_PURGE_AT=bad)

# ------------------------------------------------------------------ the clean-up of autoid.db
def seeded(s):
    today = s.app.today(); day = lambda n: (today - dt.timedelta(days=n)).isoformat()
    sync(s, "R1", [(1, "one", 1, None), (2, "two", 2, None), (3, "three", 3, None), (4, "four", 4, None)])
    sync(s, "R_OLD", [(9, "ancient", 1, None)], name="Old bulletin")
    for slug, n in (("one", 8), ("two", 7), ("three", 6), ("ancient", 9)): run(s, "UPDATE clip_ids SET day=? WHERE story_id=(SELECT id FROM stories WHERE slug=?)", (day(n), slug))
    run(s, "UPDATE stories SET last_seen_at=? WHERE slug IN ('one','ancient')", ((today - dt.timedelta(days=9)).isoformat() + "T10:00:00Z",))
    run(s, "UPDATE rundowns SET air_date=? WHERE blaze_rundown_id='R_OLD'", (day(9),))
    run(s, "INSERT INTO files(clip_id, state, created_at) VALUES(?, 'ON_NITRO', 'x')", (clip_of(s, "one"),)); run(s, "INSERT INTO files(clip_id, state, created_at) VALUES(?, 'ON_NITRO', 'x')", (clip_of(s, "three"),))
    run(s, "INSERT INTO clip_old_names(clip_id, name, changed_at) VALUES(?, 'OLD', 'x')", (clip_of(s, "one"),))
    for t in ("2020-01-01T00:00:00Z", day(9) + "T08:00:00Z", day(6) + "T08:00:00Z"): run(s, "INSERT INTO events(time, actor, action, details) VALUES(?, 't', 'old', '{}')", (t,))
    return today

def test_the_clean_up_keeps_the_last_7_days_and_removes_the_rest(s):
    today = seeded(s); out = s.app.purge_old("test")
    assert out["clips"] == 3 and out["files"] == 1 and out["stories"] == 2 and out["rundowns"] == 1       # day -8, -7 and -9 go; -6 (the oldest day kept) and today stay
    left = sorted(r["slug"] for r in sql(s, "SELECT slug FROM stories")); assert left == ["four", "three", "two"]       # "two" has no clip left but was seen recently: kept
    assert [r["blaze_rundown_id"] for r in sql(s, "SELECT blaze_rundown_id FROM rundowns")] == ["R1"]
    assert cnt(s, "files") == 1 and cnt(s, "clip_old_names") == 0 and sorted(r["day"] for r in sql(s, "SELECT day FROM clip_ids")) == [(today - dt.timedelta(days=6)).isoformat(), today.isoformat()]
    ev = sql(s, "SELECT time FROM events WHERE action='old' ORDER BY time"); assert len(ev) == 1 and ev[0]["time"].startswith((s.app.today() - dt.timedelta(days=6)).isoformat())
    assert out["events"] >= 2 and sql(s, "SELECT COUNT(*) n FROM events WHERE actor='retention' AND action='purged'")[0]["n"] == 1

def test_the_event_log_stays_append_only_after_a_clean_up(s):
    seeded(s); s.app.purge_old("test")
    with pytest.raises(sqlite3.IntegrityError): run(s, "DELETE FROM events")
    with pytest.raises(sqlite3.IntegrityError): run(s, "UPDATE events SET actor='x'")

def test_a_second_clean_up_has_nothing_to_do_and_makes_no_backup(s):
    seeded(s); first = s.app.purge_old("test"); assert first["backup"]
    n = len(list((s.tmp / "backups").glob("*.db"))); again = s.app.purge_old("test")
    assert again["clips"] == 0 and again["events"] == 0 and again["backup"] is None and len(list((s.tmp / "backups").glob("*.db"))) == n == 1

def test_a_backup_is_made_before_deleting_and_only_the_newest_three_are_kept(s):
    for i in range(4):
        run(s, "INSERT INTO events(time, actor, action, details) VALUES('2020-01-01T00:00:00Z', 't', 'old', '{}')"); out = s.app.purge_old("test"); assert out["backup"]
        if i < 3: time.sleep(1.1)
    b = sorted((s.tmp / "backups").glob("autoid-before-cleanup-*.db")); assert len(b) == 3
    c = sqlite3.connect(str(b[-1])); assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] >= 1; c.close()      # a real, readable copy

def test_keep_days_0_deletes_nothing(tmp_path):
    x = Srv(tmp_path, "story_id", {"AUTOID_KEEP_DAYS": "0"}); x.login(); x.tmp = tmp_path; seeded(x); n = cnt(x, "clip_ids")
    assert x.app.purge_old("test") == {"skipped": "AUTOID_KEEP_DAYS is 0"} and cnt(x, "clip_ids") == n and not x.app.retention_due()
    st, b = x.call("POST", "/api/retention/run"); assert st == 409 and "AUTOID_KEEP_DAYS" in b["detail"]
    assert x.call("GET", "/api/retention")[1]["keep_days"] == 0

def test_a_longer_keep_days_keeps_more(tmp_path):
    x = Srv(tmp_path, "story_id", {"AUTOID_KEEP_DAYS": "8"}); x.login(); x.tmp = tmp_path; seeded(x); out = x.app.purge_old("test")
    assert out["clips"] == 2 and out["keeps_from"] == (x.app.today() - dt.timedelta(days=7)).isoformat()       # day -9 and day -8 go; day -7 (the oldest of the 8 days) stays

def test_the_clean_up_gives_the_space_back(s):
    big = "x" * 2000
    with s.app.db.tx() as cur:
        for i in range(3500): cur.x("INSERT INTO events(time, actor, action, details) VALUES('2020-01-01T00:00:00Z', 't', 'old', ?)", (big,))
    out = s.app.purge_old("test"); assert out["events"] == 3500 and out["compacted"] is True and out["db_mb_after"] < out["db_mb_before"] / 4

def test_the_clean_up_is_due_once_a_day_from_the_set_time(s):
    app = s.app; at = lambda h, m: dt.datetime.combine(app.now().date(), dt.time(h, m))
    app.cfg["purge_at"] = "03:30"; assert not app.retention_due(at(3, 29)) and app.retention_due(at(3, 30)) and app.retention_due(at(15, 0))
    app.purge_old("scheduled")
    assert not app.retention_due(at(15, 0)) and app.retention_due(at(15, 0) + dt.timedelta(days=1))

def test_the_retention_api_shows_the_state_and_only_an_admin_can_run_it(s):
    st, b = s.call("GET", "/api/retention"); today = s.app.today()
    assert st == 200 and b["keep_days"] == 7 and b["keeps_from"] == (today - dt.timedelta(days=6)).isoformat() and b["purge_at"] == "03:30" and b["last"] is None and b["db_mb"] >= 0
    assert s.call("GET", "/api/config")[1]["keep_days"] == 7
    st, out = s.call("POST", "/api/retention/run"); assert st == 200 and out["why"].startswith("manual: ") and s.call("GET", "/api/retention")[1]["last"]["date"]
    s.call("POST", "/api/users", {"email": "ed@x.io", "password": "editorpass", "role": "editor", "valid_upto": "2999-01-01"}); s.login("ed@x.io", "editorpass")
    assert s.call("GET", "/api/retention")[0] == 200 and s.call("POST", "/api/retention/run")[0] == 403

def test_the_clean_up_does_not_stop_the_dashboard_or_new_stories(s):
    seeded(s); s.app.purge_old("test")
    assert sync(s, "R1", [(1, "one", 1, None), (4, "four", 4, None), (7, "seven", 5, None)])["stories"] == 3 and "seven" in slugs(lst(s))

# ------------------------------------------------------------------ the poller's own file
def test_the_poller_ledger_drops_what_is_older_than_the_kept_days(tmp_path):
    L = Ledger(tmp_path / "l.db"); now = time.time(); d = 86400
    L.c.execute("INSERT INTO plan VALUES('old','1','2','3','t',?)", (now - 9 * d,)); L.c.execute("INSERT INTO plan VALUES('new','1','2','3','t',?)", (now - 2 * d,))
    L.c.execute("INSERT INTO seen VALUES('old','1','2','3','t',1,?)", (now - 9 * d,)); L.c.execute("INSERT INTO seen VALUES('new','1','2','3','t',1,?)", (now - d,))
    L.c.execute("INSERT INTO live VALUES('old','1','2','3','t',?, 'SENT', NULL, NULL)", (now - 9 * d,)); L.c.execute("INSERT INTO live VALUES('new','1','2','3','t',?, 'SENT', NULL, NULL)", (now,))
    L.prune(now, 7)
    for t in ("plan", "seen", "live"): assert [r[0] for r in L.c.execute("SELECT display_id FROM %s" % t)] == ["new"]

def test_the_poller_snapshot_days_follow_the_keep_days_unless_set_on_their_own():
    assert bp.Cfg({}).snap_days == 7 and bp.Cfg({}).keep_days == 7
    assert bp.Cfg({"AUTOID_KEEP_DAYS": "30"}).snap_days == 30 and bp.Cfg({"AUTOID_KEEP_DAYS": "0"}).snap_days == 14 and bp.Cfg({"AUTOID_KEEP_DAYS": "0"}).keep_days == 0
    assert bp.Cfg({"AUTOID_KEEP_DAYS": "7", "BLAZE_SNAPSHOT_KEEP_DAYS": "3"}).snap_days == 3

# ------------------------------------------------------------------ sorting
def test_sort_by_row_number_ascending_and_descending_keeps_the_bulletins_in_order(s):
    sync(s, "10", [(1, "a1", 3, None), (2, "a2", 1, None), (3, "a3", 2, None), (4, "a4", None, None)], "First")
    sync(s, "20", [(5, "b1", 2, None), (6, "b2", 1, None)], "Second")
    assert slugs(lst(s, sort="row", dir="asc")) == ["a2", "a3", "a1", "a4", "b2", "b1"]
    assert slugs(lst(s, sort="row", dir="desc")) == ["a1", "a3", "a2", "a4", "b1", "b2"]       # no row number: always last; the bulletins keep their order
    assert slugs(lst(s, sort="row")) == slugs(lst(s, sort="row", dir="asc"))

def test_sort_by_title_ignores_case_uses_the_story_name_or_the_slug_and_pages_correctly(s):
    sync(s, "10", [(1, "z-slug", 1, "banana"), (2, "q", 2, "Apple"), (3, "cherry", 3, None), (4, "Date", 4, "")])
    shown = lambda b: [c["story_title"] or c["slug"] for c in b["clips"]]
    assert shown(lst(s, sort="title", dir="asc")) == ["Apple", "banana", "cherry", "Date"] and shown(lst(s, sort="title", dir="desc")) == ["Date", "cherry", "banana", "Apple"]
    assert shown(lst(s, sort="title", dir="asc", per_page=2, page=1)) + shown(lst(s, sort="title", dir="asc", per_page=2, page=2)) == ["Apple", "banana", "cherry", "Date"]       # the sort is across the whole day, not only the page on screen

def test_sort_by_status_puts_the_clips_that_need_the_desk_first(s):
    sync(s, "10", [(i, n, i, None) for i, n in enumerate(("w", "att", "nit", "nd", "sub", "q"), 1)])
    for n, st in (("att", "ATTACHED"), ("nit", "ON_NITRO"), ("nd", "NEEDS_DESK"), ("sub", "ATTACH_SUBMITTED"), ("q", "QUARANTINED")): run(s, "UPDATE clip_ids SET state=? WHERE id=?", (st, clip_of(s, n)))
    assert slugs(lst(s, sort="status", dir="asc")) == ["nd", "q", "nit", "sub", "w", "att"] and slugs(lst(s, sort="status", dir="desc")) == ["att", "w", "sub", "nit", "q", "nd"]

def test_without_a_sort_the_default_order_is_unchanged(s):
    sync(s, "10", [(1, "a", 3, None), (2, "b", 1, None), (3, "c", 2, None)]); run(s, "UPDATE clip_ids SET state='ON_NITRO' WHERE id=?", (clip_of(s, "a"),))
    assert slugs(lst(s)) == ["a", "b", "c"]       # needing action first, then the row order

def test_a_wrong_sort_or_direction_is_refused(s):
    assert s.call("GET", "/api/clips?per_page=10&sort=name")[0] == 400 and s.call("GET", "/api/clips?per_page=10&sort=row&dir=up")[0] == 400

# ------------------------------------------------------------------ removed stories
def removed_setup(s):
    sync(s, "10", [(1, "live", 1, None), (2, "gone-wait", 2, None), (3, "gone-nitro", 3, None), (4, "gone-held", 4, None), (5, "gone-done", 5, None)])
    for n in ("gone-wait", "gone-nitro", "gone-held", "gone-done"): run(s, "UPDATE stories SET deleted=1, deleted_at='x', deleted_reason='r' WHERE slug=?", (n,))
    for n, st in (("gone-nitro", "ON_NITRO"), ("gone-held", "NEEDS_DESK"), ("gone-done", "ATTACHED")): run(s, "UPDATE clip_ids SET state=? WHERE id=?", (st, clip_of(s, n)))

def test_the_removed_filter_lists_only_the_struck_out_stories_and_counts_them(s):
    removed_setup(s); b = lst(s, filter="removed")
    assert sorted(slugs(b)) == ["gone-done", "gone-held", "gone-nitro", "gone-wait"] and b["total"] == 4 and b["counts"]["removed"] == 4 and all(c["deleted"] for c in b["clips"])
    assert b["counts"]["all"] == 5 and lst(s)["counts"]["removed"] == 4       # the other counts stay whole; the removed count is there in every view
    assert [x["m"] for x in b["bulletins"]] == [4]

def test_hide_removed_leaves_out_only_the_struck_out_stories_that_need_nothing(s):
    removed_setup(s); b = lst(s, hide_removed=1)
    assert sorted(slugs(b)) == ["gone-held", "gone-nitro", "live"] and b["total"] == 3       # struck out and waiting / attached: hidden; still on Nitro or held: shown, they need the desk
    assert b["counts"]["all"] == 3 and b["counts"]["removed"] == 4 and lst(s, hide_removed=0)["total"] == 5
    assert sorted(slugs(lst(s, hide_removed=1, filter="removed"))) == ["gone-done", "gone-held", "gone-nitro", "gone-wait"]       # asking for the removed ones wins over the switch
    assert sorted(slugs(lst(s, hide_removed=1, filter="attention"))) == ["gone-held"]

def test_removed_with_sort_and_search_work_together(s):
    removed_setup(s); assert slugs(lst(s, filter="removed", sort="title", dir="desc", q="gone-")) == ["gone-wait", "gone-nitro", "gone-held", "gone-done"]

# ------------------------------------------------------------------ the page
def test_the_page_has_the_new_controls():
    h = (pathlib.Path(__file__).resolve().parents[1] / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    for m in ('class="shb" data-k="row"', 'data-k="title"', 'data-k="status"', 'id="hrm"', 'id="srt"', 'id="keepn"', 'id="dbinfo"', '"autoid_sort"', '"autoid_hide_rm"', '["removed","Removed"', '"/api/retention"', 'id="upd"', 'Not refreshing - last updated', 'Clean up now', 'aria-sort'):
        assert m in h, m
    assert 'qs.set("sort",sortKey)' in h and h.count('qs.set("sort",sortKey)') == 2 and h.count('qs.set("hide_removed","1")') == 2      # the list and the CSV export ask the same way

# ------------------------------------------------------------------ the real page against a real server, in a headless DOM
def test_new_controls_in_a_headless_browser(s):
    import os, shutil, subprocess
    node = shutil.which("node"); root = pathlib.Path(__file__).resolve().parents[1]; js = root / "tools" / "dev" / "check_new_controls.js"
    if not node: pytest.skip("node is not installed (developer check only)")
    env = dict(os.environ); env["NODE_PATH"] = os.pathsep.join(p for p in [str(root / "tools" / "dev" / "node_modules"), env.get("NODE_PATH", "")] if p)
    if subprocess.run([node, "-e", "require('jsdom')"], env=env, capture_output=True).returncode: pytest.skip("jsdom is not installed: cd tools/dev && npm install jsdom")
    sync(s, "10", [(1, "Zulu", 1, None), (2, "alpha", 2, None), (3, "Mike", 3, "Bravo story"), (4, "charlie", 4, None), (5, "gone-wait", 5, None), (6, "gone-nitro", 6, None), (7, "gone-held", 7, None), (8, "gone-done", 8, None), (9, "echo", 9, None)])
    for n in ("gone-wait", "gone-nitro", "gone-held", "gone-done"): run(s, "UPDATE stories SET deleted=1, deleted_at='x', deleted_reason='r' WHERE slug=?", (n,))
    for n, st in (("gone-nitro", "ON_NITRO"), ("gone-held", "NEEDS_DESK"), ("gone-done", "ATTACHED"), ("echo", "ATTACHED"), ("charlie", "ATTACHED")): run(s, "UPDATE clip_ids SET state=? WHERE id=?", (st, clip_of(s, n)))
    r = subprocess.run([node, str(js), str(s.port), "admin@x.io", "adminpass1"], env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, r.stdout[-2500:] + r.stderr[-800:]
