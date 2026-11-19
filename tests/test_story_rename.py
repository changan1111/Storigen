"""v10.9.1: a story renamed in Blaze (same story ID, new title) takes its clip NAME with it while no file is on its way; the old name gets a clear refusal; a clip whose file is already there keeps its name."""
import sys, pathlib, datetime as dt
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from test_blaze_poll import bp, env, live_env, ready_clip, posts, clips, slug       # noqa: F401  (fixtures)
from test_story_scripts import row
from test_server import sid                                                          # noqa: F401
from autoid_lite.ids import name_id

TODAY = lambda: dt.date.today()
def nm(title, day=None): return name_id(day or TODAY(), title, "900")
def sync(s, title, story="900", rundown="R1", slug_id="1"): return s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": rundown, "rundown_name": "Bulletin", "stories": [{"blaze_story_id": story, "slug": title, "slug_id": slug_id, "position": 1}]})
def names(s): return sorted((c["name_id"], c["state"], c["slug"]) for c in s.call("GET", "/api/clips")[1]["clips"])
def match(s, name): return s.svc("GET", "/svc/match?name=" + name)

@pytest.fixture
def named(sid, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); return sid

def test_a_rename_gives_the_waiting_clip_the_new_name(named):
    s = named; assert sync(s, "karthik test")[0] == 200
    assert names(s) == [(nm("karthik test"), "WAITING_FOR_CLIP", "karthik test")]
    disp = s.call("GET", "/api/clips")[1]["clips"][0]["display_id"]
    assert sync(s, "karthik test final")[0] == 200
    got = names(s); assert got == [(nm("karthik test final"), "WAITING_FOR_CLIP", "karthik test final")]
    assert s.call("GET", "/api/clips")[1]["clips"][0]["display_id"] == disp                   # the internal ID never changes
    assert match(s, nm("karthik test final"))[0] == 200 and match(s, nm("karthik test final").lower())[0] == 200

def test_the_old_name_is_refused_and_says_what_the_name_is_now(named):
    s = named; sync(s, "karthik test"); sync(s, "karthik test final")
    st, body = match(s, nm("karthik test")); assert st == 404
    msg = str(body); assert "renamed" in msg and nm("karthik test final") in msg and nm("karthik test") in msg
    assert match(s, "191126_NEVER_EXISTED")[0] == 404 and "renamed" not in str(match(s, "191126_NEVER_EXISTED")[1])      # an unknown name stays a plain 404

def test_the_same_title_again_and_a_title_with_the_same_file_safe_name_change_nothing(named):
    s = named; sync(s, "karthik test"); sync(s, "karthik test"); assert [n for n, _, _ in names(s)] == [nm("karthik test")]
    sync(s, "Karthik  TEST!"); got = names(s); assert [n for n, _, _ in got] == [nm("karthik test")] and got[0][2] == "Karthik  TEST!"      # the title is updated, the file-safe name is the same: no new name, no refusal
    assert match(s, nm("karthik test"))[0] == 200

def test_a_clip_whose_file_is_already_on_its_way_keeps_its_name(named):
    s = named; sync(s, "karthik test")
    with s.app.db.tx() as cur: cur.x("UPDATE clip_ids SET state='ON_NITRO'")
    sync(s, "karthik test final"); got = names(s)
    assert got == [(nm("karthik test"), "ON_NITRO", "karthik test final")]                       # the file carries the old name: the clip keeps it, the story name still follows
    assert match(s, nm("karthik test"))[0] == 200

def test_every_clip_of_the_story_follows_and_keeps_its_ending(named, monkeypatch):
    monkeypatch.setenv("VERSION_SUFFIX", "on"); s = named; sync(s, "karthik test")
    assert match(s, nm("karthik test") + "_U01")[0] == 200 and match(s, nm("karthik test") + "_V01")[0] == 200       # an update and an added clip, both made from the file name
    sync(s, "karthik test final"); got = [n for n, _, _ in names(s)]
    assert got == sorted([nm("karthik test final"), nm("karthik test final") + "_U01", nm("karthik test final") + "_V01"])
    assert match(s, nm("karthik test final") + "_U01")[0] == 200
    st, body = match(s, nm("karthik test") + "_U01"); assert st == 404 and nm("karthik test final") + "_U01" in str(body)

def test_a_story_in_two_bulletins_is_renamed_where_it_changed(named):
    s = named; sync(s, "karthik test", rundown="R1"); sync(s, "karthik test", rundown="R2")
    assert len(names(s)) == 1 or len({n for n, _, _ in names(s)}) == 1                          # one shared clip name
    sync(s, "karthik test final", rundown="R1"); got = {n for n, _, _ in names(s)}
    assert nm("karthik test final") in got

def test_a_rename_is_written_to_the_event_log_and_the_desk_is_alerted(named, monkeypatch):
    told = []; monkeypatch.setattr(type(named.app), "alert", lambda self, text: told.append(text))
    s = named; sync(s, "karthik test"); assert told == []
    sync(s, "karthik test final"); assert len(told) == 1 and "karthik test" in told[0] and nm("karthik test final") in told[0] and nm("karthik test") in told[0]
    with s.app.db.tx() as cur: ev = cur.q("SELECT details FROM events WHERE action='story_renamed'")
    assert len(ev) == 1 and nm("karthik test final") in ev[0]["details"]
    sync(s, "karthik test final"); assert len(told) == 1                                          # nothing changed: nothing said again

def test_the_legacy_id_format_is_left_alone(sid, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "legacy"); s = sid; sync(s, "karthik test"); before = s.call("GET", "/api/clips")[1]["clips"][0]
    sync(s, "karthik test final"); after = s.call("GET", "/api/clips")[1]["clips"][0]
    assert after["display_id"] == before["display_id"] and after["slug"] == "karthik test final"

def test_the_poller_carries_a_rename_all_the_way(env, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); s, f, p = env; assert s.login()[0] == 200
    f.slugs = [slug(724921, "karthik test", 1)]; p.cycle(); r = row(s, 724921); first = r["name_id"]; assert "KARTHIK_TEST" in first and r["slug"] == "karthik test"
    f.slugs = [slug(724921, "karthik test final", 1)]; p.cycle(); r = row(s, 724921)
    assert r["slug"] == "karthik test final" and r["name_id"] == first + "_FINAL" and r["state"] == "WAITING_FOR_CLIP"
    assert len(s.call("GET", "/api/clips")[1]["clips"]) == 1                                     # renamed, not deleted and made again

# ---------------------------------------------------------------- v10.9.2: Blaze gives the renamed story a NEW story ID in the same slug
def rows_all(s): return [(c["blaze_story_id"], c["slug"], c["name_id"], c["state"], bool(c["deleted"]), c["display_id"]) for c in s.call("GET", "/api/clips?per_page=100")[1]["clips"]]
def test_a_new_story_id_in_the_same_slug_updates_the_row_instead_of_striking_it_out(named):
    s = named; sync(s, "karthik test", story="900"); before = rows_all(s); assert len(before) == 1
    sync(s, "karthik test final", story="901"); got = rows_all(s)
    assert len(got) == 1 and got[0][:5] == ("901", "karthik test final", nm("karthik test final"), "WAITING_FOR_CLIP", False) and got[0][5] == before[0][5]      # one row, not struck out, same internal ID
    assert match(s, nm("karthik test final"))[0] == 200 and match(s, nm("karthik test"))[0] == 404

def test_a_clip_that_already_has_its_file_is_not_adopted(named):
    s = named; sync(s, "karthik test", story="900")
    with s.app.db.tx() as cur: cur.x("UPDATE clip_ids SET state='ON_NITRO'")
    sync(s, "karthik test final", story="901"); got = sorted(rows_all(s))
    assert [(g[0], g[4]) for g in got] == [("900", True), ("901", False)]                       # as before: the old story is struck out, the new one gets its own clip

def test_without_a_slug_id_or_with_a_different_slug_nothing_is_adopted(named):
    s = named; sync(s, "karthik test", story="900", slug_id="1"); sync(s, "karthik test final", story="901", slug_id="2")
    assert sorted((g[0], g[4]) for g in rows_all(s)) == [("900", True), ("901", False)]
    t = named; 
    assert t.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "R9", "stories": [{"blaze_story_id": "1", "slug": "a"}]})[0] == 200
    assert t.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "R9", "stories": [{"blaze_story_id": "2", "slug": "b"}]})[0] == 200
    assert sorted((g[0], g[4]) for g in rows_all(t) if g[0] in ("1", "2")) == [("1", True), ("2", False)]

def test_a_story_that_stays_in_the_list_is_never_adopted_by_another(named):
    s = named
    assert s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "R1", "stories": [{"blaze_story_id": "900", "slug": "one", "slug_id": "1"}, {"blaze_story_id": "902", "slug": "two", "slug_id": "2"}]})[0] == 200
    assert s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "R1", "stories": [{"blaze_story_id": "900", "slug": "one", "slug_id": "1"}, {"blaze_story_id": "903", "slug": "two b", "slug_id": "1"}]})[0] == 200      # 903 claims slug 1, but 900 is still listed there
    got = {g[0]: g for g in rows_all(s)}; assert got["900"][4] is False and got["903"][4] is False and got["902"][4] is True and got["903"][2] == nm("two b")

def test_a_title_without_latin_letters_follows_too(named):
    s = named; sync(s, "கார்த்திக் டெஸ்ட்", story="900"); first = rows_all(s)[0]; assert first[2].endswith("_S900")
    sync(s, "karthik test", story="901"); got = rows_all(s)
    assert len(got) == 1 and got[0][0] == "901" and got[0][2] == nm("karthik test") and got[0][4] is False and got[0][5] == first[5]

def test_the_poller_updates_the_row_when_blaze_gives_a_new_story_id(env, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); s, f, p = env; assert s.login()[0] == 200
    f.slugs = [slug(724921, "karthik test", 1)]; p.cycle(); first = row(s, 724921); assert first["slug"] == "karthik test"
    sl = slug(724999, "karthik test final", 1); sl["id"] = 724921 + 1000; f.slugs = [sl]; p.cycle()
    allc = s.call("GET", "/api/clips?per_page=100")[1]["clips"]
    assert len(allc) == 1 and allc[0]["blaze_story_id"] == "724999" and not allc[0]["deleted"] and allc[0]["slug"] == "karthik test final" and allc[0]["name_id"] == first["name_id"] + "_FINAL"
