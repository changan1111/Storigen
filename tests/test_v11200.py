"""v11.2.0: (1) a story whose clip is not attached yet says 0 clips, not 1; (2) the plain (base) clip takes a (byte) / (minibyte) / (tag) / (del) label like _V01 / _U01 do;
(3) the chat shows the label of the clips that are already in the story."""
import sys, pathlib, importlib, urllib.parse
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pytest
from test_server import Srv
from autoid_lite import ids, coach
from autoid_lite.blaze import keys
from autoid_lite.api_blazeclips import merge_blaze, parse_clip_name
from autoid_lite.api_bot import clip_labels

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def on(monkeypatch): monkeypatch.setenv("VERSION_SUFFIX", "on")


# ---------------------------------------------------------------- 2) the base clip takes a label
@pytest.mark.parametrize("raw", ["221126_ELECTION (byte)", "221126_ELECTION (BYTE)", "221126_ELECTION  (tag)", "221126_ELECTION (del)", "221126_ELECTION (minibyte)", "221126_ELECTION (mini byte)",
                                 "221126_ELECTION_(byte)", "221126_ELECTION (byte) (tag)"])
def test_a_bracketed_label_at_the_end_of_the_plain_clip_is_dropped(raw): assert ids.strip_label(raw) == "221126_ELECTION"


@pytest.mark.parametrize("raw", ["221126_MODI_BYTE", "221126_FIRE_TAG", "221126_FIRE_DEL", "221126_FIRE BYTE", "221126_FIRE (2)", "221126_FIRE_2", "221126_FIRE (byte) NEWS", "221126_FIRE (del)_V01 x", "221126_FIRE (hello)"])
def test_story_words_copy_numbers_and_other_brackets_are_left_alone(raw): assert ids.strip_label(raw) == raw


def test_the_labels_after_a_version_work_as_before():
    assert ids.strip_label("221126_FIRE_V01 (byte)") == "221126_FIRE_V01" and ids.strip_label("221126_FIRE_V01 (byte)_U01") == "221126_FIRE_V01_U01"
    assert ids.strip_label("221126_FIRE_V01_U01 (del)") == "221126_FIRE_V01_U01" and ids.strip_label("221126_FIRE_V01 byte") == "221126_FIRE_V01" and ids.strip_label("221126_FIRE_U02 (anything)") == "221126_FIRE_U02"


@pytest.mark.parametrize("raw,clean", [("221126_FIRE_V01 byte", "221126_FIRE_V01"), ("221126_FIRE_V01_byte", "221126_FIRE_V01"), ("221126_FIRE_V01-byte", "221126_FIRE_V01"), ("221126_FIRE_V01_minibyte", "221126_FIRE_V01"),
                                       ("221126_FIRE_V01_mini_byte", "221126_FIRE_V01"), ("221126_FIRE_V01_tag", "221126_FIRE_V01"), ("221126_FIRE_U01_byte", "221126_FIRE_U01"), ("221126_FIRE_V01_U01_byte", "221126_FIRE_V01_U01")])
def test_after_a_version_the_plain_word_needs_no_brackets(raw, clean): assert ids.strip_label(raw) == clean


@pytest.mark.parametrize("raw", ["221126_FIRE_V01_del", "221126_FIRE_V01_byte_U01"])
def test_known_limits_after_a_version(raw): assert ids.strip_label(raw) == raw      # `del` is a label only in brackets; a plain word is only read at the very end (in the middle use brackets)


def test_nothing_changes_when_the_switch_is_off(monkeypatch):
    monkeypatch.setenv("VERSION_SUFFIX", "off"); assert ids.strip_label("221126_ELECTION (byte)") == "221126_ELECTION (byte)"
    assert keys.media_key("221126_ELECTION (byte).mxf") == ("221126_ELECTION_BYTE", 1)           # as before: the brackets were just punctuation


def test_label_of():
    assert ids.label_of("221126_ELECTION (byte)") == "byte" and ids.label_of("221126_ELECTION (Mini Byte)") == "minibyte" and ids.label_of("221126_ELECTION (del)") == "del"
    assert ids.label_of("221126_FIRE_V01 (tag)") == "tag" and ids.label_of("221126_FIRE_V01_U01 (byte)") == "byte" and ids.label_of("221126_FIRE_V01 byte") == "byte"
    assert ids.label_of("221126_ELECTION") == "" and ids.label_of("221126_MODI_BYTE") == "" and ids.label_of("221126_FIRE (2)") == ""


def test_matching_keys_ignore_the_label_of_the_plain_clip():
    plain = keys.media_key("221126_ELECTION.mxf"); assert plain == ("221126_ELECTION", 1)
    for lab in ("byte", "minibyte", "tag", "del"): assert keys.media_key("221126_ELECTION (%s).mxf" % lab) == plain
    assert keys.name_key("221126_ELECTION (byte)") == plain and keys.ver_split("221126_ELECTION (byte)") == ("221126_ELECTION", 1)
    assert keys.media_key("221126_MODI_BYTE.mxf") == ("221126_MODI_BYTE", 1), "a story called MODI BYTE keeps its own name"
    assert parse_clip_name("221126_ELECTION (tag).mxf") == ("221126_ELECTION", 1)
    assert ids.split_suffix(ids.norm_name("221126_ELECTION (byte)")) is None and ids.name_base("221126_ELECTION (byte)") == "221126_ELECTION"


def test_the_poller_finds_a_labelled_plain_file_for_the_plain_clip():
    m = {"id": 7, "title": "221126_ELECTION (byte)", "status": "UPDATED", "duration": 5000, "modifiedDate": "2026-01-01T00:00:00+00:00"}
    st, got = keys.find_media([m], keys.clip_key("221126_ELECTION", 1), 0); assert st == "found" and got["id"] == 7
    st, got = keys.find_indexed(keys.index_media([m]), keys.clip_key("221126_ELECTION", 1), 0); assert st == "found" and got["id"] == 7


def test_watcher_parse_name():
    import autoid_lite.watcher as w; importlib.reload(w)
    plain = w.parse_name("221126_ELECTION.mxf"); assert plain == ("NAME", "221126_ELECTION", 1, None)
    for lab in ("byte", "minibyte", "tag", "del"): assert w.parse_name("221126_ELECTION (%s).mxf" % lab) == plain
    assert w.parse_name("221126_MODI_BYTE.mxf") == ("NAME", "221126_MODI_BYTE", 1, None) and w.parse_name("221126_FIRE (2).mxf") == ("NAME", "221126_FIRE_2", 1, None)
    assert w.parse_name("221126_FIRE_V01 (byte).mxf") == ("NAME", "221126_FIRE_V01", 2001, None)


def test_the_watcher_does_nothing_new_when_the_switch_is_off(monkeypatch):
    monkeypatch.setenv("VERSION_SUFFIX", "off")
    import autoid_lite.watcher as w; importlib.reload(w)
    try: assert w.parse_name("221126_ELECTION (byte).mxf") == ("NAME", "221126_ELECTION_BYTE", 1, None)
    finally: monkeypatch.setenv("VERSION_SUFFIX", "on"); importlib.reload(w)


def test_coach_accepts_a_labelled_plain_name():
    plan = {"main": None, "added": [], "next_v": "221126_ELECTION_V01", "next_v_no": 1}
    r = coach.check_name(plan, "221126_ELECTION", "221126_ELECTION (byte).mxf"); assert r["ok"] and r["kind"] == "main" and r["label"] == "byte"
    assert any("(byte)" in m and "only for people" in m for m in r["messages"])
    assert coach.check_name(plan, "221126_ELECTION", "221126_ELECTION (del)")["label"] == "del"
    assert coach.check_name(plan, "221126_ELECTION", "221126_OTHER (byte)")["kind"] == "wrong_base"
    assert coach.check_name(plan, "221126_ELECTION", "221126_ELECTION_BYTE")["kind"] == "wrong_base", "a different story name is still refused"
    assert coach.check_name(plan, "221126_ELECTION", "221126_ELECTION", True)["label"] == ""
    assert coach.check_name(plan, "221126_ELECTION", "221126_ELECTION (byte)", suffix_on=False)["kind"] == "wrong_base"
    plan = {"main": {"current": "221126_ELECTION", "next_u": 1, "next_u_name": "221126_ELECTION_U01"}, "added": [], "next_v": "221126_ELECTION_V01", "next_v_no": 1}
    assert coach.check_name(plan, "221126_ELECTION", "221126_ELECTION (byte)")["kind"] == "exists", "the plain clip is already there: the coach still says so"


def test_the_server_matches_a_labelled_plain_name(tmp_path, monkeypatch):
    s, cid, base = story(tmp_path, monkeypatch, attached=False)
    for nm in (base, base + " (byte)", base + " (del)", base.lower() + " (Tag)"):
        st, body = s.svc("GET", "/svc/match?name=" + urllib.parse.quote(nm)); assert st == 200 and body["name_id"].upper() == base.upper(), (nm, st, body)


# ---------------------------------------------------------------- 1) 0 clips until one is attached
def story(tmp_path, monkeypatch, attached=True, suffix="on"):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("VERSION_SUFFIX", suffix)
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    r = s.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO1", "blaze_story_id": "740371", "slug": "KARTHIK CLIP CHECK", "rundown_name": "21:30 Bulletin"}); assert r[0] == 200, r
    with s.app.db.tx() as cur:
        c = cur.q("SELECT c.id, COALESCE(c.name_id, c.display_id) AS nm FROM clip_ids c JOIN stories st ON st.id=c.story_id WHERE st.blaze_story_id='740371' ORDER BY c.id")[0]
        if attached: cur.x("UPDATE clip_ids SET state='ATTACHED', media_id='1126526', blaze_clip_id='957411' WHERE id=?", (c["id"],))
    return s, c["id"], c["nm"]


def row(s, cid): return [x for x in s.call("GET", "/api/clips")[1]["clips"] if x["id"] == cid][0]


@pytest.mark.parametrize("suffix", ["on", "off"])
def test_a_story_with_no_attached_clip_has_zero_clips(tmp_path, monkeypatch, suffix):
    s, cid, base = story(tmp_path, monkeypatch, attached=False, suffix=suffix)
    assert row(s, cid)["story_clips"] == 0 and row(s, cid)["state"] != "ATTACHED"


@pytest.mark.parametrize("suffix", ["on", "off"])
def test_the_count_follows_what_is_really_in_the_story(tmp_path, monkeypatch, suffix):
    s, cid, base = story(tmp_path, monkeypatch, suffix=suffix); assert row(s, cid)["story_clips"] == 1
    with s.app.db.tx() as cur:      # a second clip ID that is still waiting does not count; an attached one does
        cur.x("INSERT INTO clip_ids(display_id, day, seq, story_id, version, state, created_at, name_id) SELECT display_id || '_V2', day, seq + 500, story_id, 2, 'WAITING_FOR_CLIP', created_at, COALESCE(name_id, display_id) || '_V2' FROM clip_ids WHERE id=?", (cid,))
    assert row(s, cid)["story_clips"] == 1
    with s.app.db.tx() as cur: cur.x("UPDATE clip_ids SET state='ATTACHED' WHERE display_id LIKE '%\\_V2' ESCAPE '\\'")
    assert row(s, cid)["story_clips"] == 2
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "957411", "mos": "1126526", "title": "BASE"}, {"id": "9", "mos": "1", "title": "x"}, {"id": "10", "mos": "2", "title": "y"}]})
    assert row(s, cid)["story_clips"] == 2 + 2 and row(s, cid)["hand_clips"] == 2, "clips added by hand in Blaze still count"


def test_a_clip_added_by_hand_counts_even_when_the_registry_clip_is_not_attached(tmp_path, monkeypatch):
    s, cid, base = story(tmp_path, monkeypatch, attached=False)
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "9", "mos": "1", "title": "HAND"}]}); assert row(s, cid)["story_clips"] == 1


def test_the_clips_sort_uses_the_same_number(tmp_path, monkeypatch):
    s, cid, base = story(tmp_path, monkeypatch, attached=False)
    s.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO1", "blaze_story_id": "740372", "slug": "SECOND STORY", "rundown_name": "21:30 Bulletin"})
    with s.app.db.tx() as cur: cur.x("UPDATE clip_ids SET state='ATTACHED', media_id='5', blaze_clip_id='6' WHERE story_id=(SELECT id FROM stories WHERE blaze_story_id='740372')")
    desc = [x["story_clips"] for x in s.call("GET", "/api/clips?sort=clips&dir=desc")[1]["clips"]]; asc = [x["story_clips"] for x in s.call("GET", "/api/clips?sort=clips&dir=asc")[1]["clips"]]
    assert desc == [1, 0] and asc == [0, 1]


def test_the_page_does_not_count_a_waiting_clip_as_a_clip():
    assert 'typeof c.story_clips==="number"?c.story_clips:' in PAGE and 'x.state==="ATTACHED"&&!x.replaced_at' in PAGE
    assert "||(clips.filter(x=>x.story_id===c.story_id).length" not in PAGE, "the old fallback that made every waiting story say 1"
    assert 'rest?" · "+rest+" not attached":""' in PAGE and "x.by_hand||(x.state===\"ATTACHED\"&&!x.replaced)" in PAGE


# ---------------------------------------------------------------- 3) the chat shows byte / minibyte / tag / del
def test_clip_labels_reads_the_file_names_and_blaze_has_the_last_word():
    rows = [{"id": 1, "name_id": "221126_FIRE"}, {"id": 2, "name_id": "221126_FIRE_V01"}, {"id": 3, "name_id": "221126_FIRE_V02"}, {"name_id": "221126_FIRE_V03", "label": "tag"}]
    files = [{"clip_id": 1, "name": "/nas/221126_FIRE (byte).mxf"}, {"clip_id": 2, "name": r"D:\playout\221126_FIRE_V01 (minibyte).mxf"}, {"clip_id": 3, "name": "221126_FIRE_V02.mxf"}]
    assert clip_labels(rows, [], files) == {"221126_FIRE": "byte", "221126_FIRE_V01": "minibyte", "221126_FIRE_V03": "tag"}
    got = clip_labels(rows, [{"title": "221126_FIRE (del).mxf"}, {"title": "221126_FIRE_V01.mxf"}], files)
    assert got["221126_FIRE"] == "del" and "221126_FIRE_V01" not in got, "Blaze holds V01 without a label"
    assert clip_labels([{"id": 1, "name_id": "221126_FIRE_V01"}], [], [{"clip_id": 1, "name": "221126_FIRE_V01 (byte).mxf"}, {"clip_id": 1, "name": "221126_FIRE_V01 (tag).mxf"}]) == {"221126_FIRE_V01": "tag"}, "the newest file name wins"
    assert clip_labels([{"id": 1, "name_id": "221126_MODI_BYTE"}], [], [{"clip_id": 1, "name": "221126_MODI_BYTE.mxf"}]) == {}, "a story called BYTE has no label"


def test_clip_labels_is_off_with_the_switch(monkeypatch):
    monkeypatch.setenv("VERSION_SUFFIX", "off"); assert clip_labels([{"id": 1, "name_id": "221126_FIRE"}], [{"title": "221126_FIRE (byte)"}], [{"clip_id": 1, "name": "221126_FIRE (byte).mxf"}]) == {}


def test_merge_blaze_knows_a_labelled_clip_and_keeps_the_label_of_a_hand_clip():
    rows = [{"name_id": "221126_FIRE", "version": 1, "state": "ATTACHED"}, {"name_id": "221126_FIRE_V01", "version": 2001, "state": "ATTACHED"}]
    b = [{"id": "1", "title": "221126_FIRE (byte)"}, {"id": "2", "title": "221126_FIRE_V01 (minibyte)"}, {"id": "3", "title": "221126_FIRE_V02 (tag)"}, {"id": "4", "title": "OTHER"}]
    out, others = merge_blaze("221126_FIRE", rows, b)
    assert [o["name"] for o in others] == ["OTHER"], "a labelled clip that is in the registry is not a 'different name'"
    hand = [x for x in out if x.get("by_hand")]; assert len(hand) == 1 and hand[0]["name_id"] == "221126_FIRE_V02" and hand[0]["version"] == 2002 and hand[0]["label"] == "tag"


def test_the_chat_shows_the_label_of_every_clip_in_the_story(tmp_path, monkeypatch):
    s, cid, base = story(tmp_path, monkeypatch)
    q = "/api/bot/story?rundown=RO1&story=740371"; p = s.call("GET", q)[1]; assert p["clips"][0]["label"] == "" and p["main"]["current_label"] == "", "no label: nothing is made up"
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "957411", "mos": "1126526", "title": base + " (byte)"}, {"id": "957500", "mos": "1", "title": base + "_V01 (minibyte)"}]})
    p = s.call("GET", q)[1]
    assert [(x["name"], x["label"]) for x in p["clips"]] == [(base, "byte"), (base + "_V01", "minibyte")], p["clips"]
    assert p["main"]["current_label"] == "byte" and p["next_v"] == base + "_V02" and p["other_clips"] == []


def test_the_chat_reads_the_label_from_the_file_name_the_watcher_saw(tmp_path, monkeypatch):
    s, cid, base = story(tmp_path, monkeypatch)
    with s.app.db.tx() as cur: cur.x("INSERT INTO files(clip_id, nas_path, state, created_at) VALUES(?,?,?,?)", (cid, "/playout/%s (del).mxf" % base, "VERIFIED", "2026-11-26T10:00:00+05:30"))
    p = s.call("GET", "/api/bot/story?rundown=RO1&story=740371")[1]; assert p["clips"][0]["label"] == "del" and p["main"]["current_label"] == "del"


def test_the_chat_page_prints_the_label():
    assert '(x.label?" ("+x.label+")":"")' in PAGE and 'x.current+(x.current_label?" ("+x.current_label+")":"")' in PAGE
    assert 'is labelled ("+x.current_label+")' in PAGE and 'f.name+(f.label?" ("+f.label+")":"")' in PAGE


def test_the_version_is_11_2():
    assert 'var APP_VER="11.2"' in PAGE and '<span class="vb">v11.2</span>' in PAGE
    assert 'APP_VERSION = "11.2"' in (ROOT / "autoid_lite" / "common.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- the whole way: watcher name -> registry -> poller -> Blaze (fake Blaze from the poller tests)
def _poller(tmp_path, monkeypatch, slug_title="FIRE"):
    from test_blaze_poll import slug, clips, live_env
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1"); monkeypatch.setenv("VERSION_SUFFIX", "on")
    s, f, p, e = live_env(tmp_path); f.slugs = [slug(724921, slug_title, 14, 20)]; p.cycle(); return s, f, p, clips(s)[0]


@pytest.mark.parametrize("label", ["byte", "minibyte", "tag", "del"])
def test_the_poller_attaches_a_plain_file_that_has_a_label(tmp_path, monkeypatch, label):
    from test_blaze_poll import media, clips, posts, set_state
    s, f, p, base = _poller(tmp_path, monkeypatch); n = base["name_id"]
    set_state(s, base["display_id"], "ON_NITRO"); f.medias = [media(1001, "%s (%s).mxf" % (n, label))]; p.cycle()
    assert [r["state"] for r in clips(s)] == ["ATTACHED"] and len(posts(f)) == 1, "the plain clip took the labelled file"
    p.cycle(); p.cycle(); assert len(posts(f)) == 1, "and it is not attached twice"


def test_a_labelled_plain_clip_and_a_labelled_added_clip_live_together_and_the_chat_tells_them_apart(tmp_path, monkeypatch):
    from test_blaze_poll import media, clips, posts, set_state
    s, f, p, base = _poller(tmp_path, monkeypatch); n = base["name_id"]
    set_state(s, base["display_id"], "ON_NITRO"); f.medias = [media(1001, n + " (byte).mxf")]; p.cycle()
    st, m = s.svc("GET", "/svc/match?name=" + urllib.parse.quote(n + "_V01")); assert st == 200      # what the watcher does with the new file: ask the registry, then report it on Nitro with the path it really had
    s.svc("POST", "/svc/files", {"display_id": m["display_id"], "state": "ON_NITRO", "nas_path": "/playout/%s_V01 (minibyte).mxf" % n, "nitro_path": "/nitro/%s_V01 (minibyte).mxf" % n})
    f.medias.append(media(1002, n + "_V01 (minibyte).mxf")); p.cycle()
    assert len(posts(f)) == 2 and {r["state"] for r in clips(s)} == {"ATTACHED"}
    p.cycle()      # the next poll reports the story's clip list as Blaze now holds it (titles with their labels); the chat also asks Blaze live
    assert s.login()[0] == 200; code, got = s.call("GET", "/api/bot/story?rundown=34427&story=724921"); assert code == 200, (code, got)
    assert [(x["name"], x["label"]) for x in got["clips"]] == [(n, "byte"), (n + "_V01", "minibyte")], got["clips"]
    assert got["main"]["current_label"] == "byte" and got["added"][0]["current_label"] == "minibyte" and got["next_v"] == n + "_V02" and got["other_clips"] == []


def test_a_story_whose_own_name_ends_in_byte_still_attaches_by_its_plain_name(tmp_path, monkeypatch):
    from test_blaze_poll import media, clips, posts, set_state
    s, f, p, base = _poller(tmp_path, monkeypatch, "MODI BYTE"); n = base["name_id"]; assert n.endswith("_MODI_BYTE"), n
    set_state(s, base["display_id"], "ON_NITRO"); f.medias = [media(1001, n + ".mxf")]; p.cycle()
    assert [r["state"] for r in clips(s)] == ["ATTACHED"] and len(posts(f)) == 1 and ids.label_of(n) == ""
