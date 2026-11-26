"""v9.7.1: the clip NAME is DDMMYY_STORY_NAME, shared by every story with that name that day; each story keeps its own internal ID. Versions go by show; accidental versions can be deleted."""
import re, sys, pathlib
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_server import Srv
from test_blaze_poll import env, slug, media
from autoid_lite import watcher as w, gateway as gw
import blaze_poll as bp

@pytest.fixture
def nm(tmp_path, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1"); s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; return s

def mk(s, rundown, story): return s.call("POST", "/api/manual", {"rundown": rundown, "story": story})[1]
def starts(s, **t):
    with s.app.db.tx() as cur:
        for name, at in t.items(): cur.x("UPDATE rundowns SET start_at=? WHERE name=?", (at, name))
def row(s, cid):
    with s.app.db.tx() as cur: return cur.one("SELECT * FROM clip_ids WHERE id=?", (cid,))
def three(s):
    a, b, c = (mk(s, r, "Fire") for r in ("R1", "R2", "R3")); starts(s, R1="2026-11-11T13:00:00+05:30", R2="2026-11-11T14:00:00+05:30", R3="2026-11-11T15:00:00+05:30"); return a, b, c

def test_97_01_the_name_is_ddmmyy_story_and_the_internal_id_stays_unique(nm):
    c = mk(nm, "14:00 Bulletin", "Opening Montage"); today = nm.app.today()
    assert c["name_id"] == today.strftime("%d%m%y") + "_OPENING_MONTAGE" and re.match(r"^\d{8}_\d{4}[A-Z]_OPENING_MONTAGE$", c["display_id"])

def test_97_02_the_same_story_name_in_several_shows_shares_one_clip_name(nm):
    a, b, c = three(nm); assert a["name_id"] == b["name_id"] == c["name_id"] and len({a["display_id"], b["display_id"], c["display_id"]}) == 3
    rows = nm.call("GET", "/api/clips")[1]["clips"]; assert {x["name_id"] for x in rows} == {a["name_id"]} and len(rows) == 3

def test_97_03_a_file_for_the_shared_name_reaches_every_story(nm):
    a, b, c = three(nm); st, m = nm.svc("GET", "/svc/match?name=" + a["name_id"].lower()); assert st == 200 and sorted(m["group"]) == sorted(x["display_id"] for x in (a, b, c))
    assert nm.svc("POST", "/svc/files", {"display_id": m["display_id"], "state": "ON_NITRO", "nas_path": "/n/x.mxf"})[1]["clips"] == 3
    assert {row(nm, x["id"])["state"] for x in (a, b, c)} == {"ON_NITRO"}
    assert nm.svc("GET", "/svc/match?name=" + a["name_id"] + "_9")[0] == 404

def test_97_04_blaze_readback_by_clip_name_marks_only_the_right_story(nm):
    a, b, c = three(nm); nm.svc("POST", "/svc/files", {"display_id": a["display_id"], "state": "ON_NITRO"}); sb, ra = nm.svc("GET", "/svc/clips")[1], None
    rb = next(x for x in sb if x["display_id"] == b["display_id"])
    r = nm.svc("POST", "/svc/attach/confirm", {"display_id": b["name_id"], "blaze_rundown_id": rb["blaze_rundown_id"], "blaze_story_id": rb["blaze_story_id"]})[1]
    assert r["ok"] and row(nm, b["id"])["state"] == "ATTACHED" and row(nm, a["id"])["state"] == "ON_NITRO" and row(nm, c["id"])["state"] == "ON_NITRO"

def test_97_05_version_scope_lists_this_show_and_the_later_ones(nm):
    a, b, c = three(nm); s = nm.call("GET", "/api/clips/%d/scope" % b["id"])[1]
    assert s["shared"] and s["new_version"] == 2 and [x["rundown"] for x in s["this"]] == ["R2"] and [x["rundown"] for x in s["later"]] == ["R2", "R3"] and s["all"] == 3

def test_97_06_a_new_version_for_this_and_later_shows_leaves_the_aired_one_alone(nm):
    a, b, c = three(nm); st, v = nm.call("POST", "/api/clips/%d/version" % b["id"], {"scope": "later"}); assert st == 200 and v["created"] == 2 and v["name_id"] == b["name_id"] + "_V2" and v["version"] == 2
    with nm.app.db.tx() as cur: rows = cur.q("SELECT c.version, c.name_id, ru.name AS r FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id ORDER BY ru.name, c.version")
    assert [(x["r"], x["version"]) for x in rows] == [("R1", 1), ("R2", 1), ("R2", 2), ("R3", 1), ("R3", 2)] and {x["name_id"] for x in rows if x["version"] == 2} == {b["name_id"] + "_V2"}
    assert nm.svc("GET", "/svc/match?name=" + b["name_id"] + "_v2")[1]["version"] == 2

def test_97_07_a_new_version_for_this_show_only(nm):
    a, b, c = three(nm); st, v = nm.call("POST", "/api/clips/%d/version" % b["id"], {"scope": "this"}); assert v["created"] == 1
    with nm.app.db.tx() as cur: assert cur.one("SELECT COUNT(*) AS n FROM clip_ids")["n"] == 4
    assert nm.call("POST", "/api/clips/%d/version" % c["id"])[1]["created"] == 1, "no scope = this story only, as before"

def test_97_08_an_accidental_version_can_be_deleted_and_the_next_one_reuses_the_number(nm):
    a, b, c = three(nm); nm.call("POST", "/api/clips/%d/version" % b["id"], {"scope": "later"})
    with nm.app.db.tx() as cur: v2 = {x["r"]: x["id"] for x in cur.q("SELECT c.id, ru.name AS r FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id WHERE c.version=2")}
    st, d = nm.call("POST", "/api/clips/%d/delete_version" % v2["R3"], {"scope": "this"}); assert d["deleted"] == 1
    st, d = nm.call("POST", "/api/clips/%d/delete_version" % v2["R2"], {"scope": "later"}); assert d["deleted"] == 1 and not d["skipped"]
    with nm.app.db.tx() as cur: assert cur.one("SELECT COUNT(*) AS n FROM clip_ids")["n"] == 3
    assert nm.call("POST", "/api/clips/%d/version" % b["id"])[1]["name_id"] == b["name_id"] + "_V2"

def test_97_09_a_version_cannot_be_deleted_once_a_file_was_seen_and_version_1_never(nm):
    a, b, c = three(nm); v = nm.call("POST", "/api/clips/%d/version" % b["id"])[1]
    assert nm.call("POST", "/api/clips/%d/delete_version" % b["id"], {})[0] == 409, "version 1 is the clip itself"
    nm.svc("POST", "/svc/files", {"display_id": v["display_id"], "state": "ON_NITRO"}); st, e = nm.call("POST", "/api/clips/%d/delete_version" % v["id"], {}); assert st == 409
    with nm.app.db.tx() as cur: assert cur.one("SELECT COUNT(*) AS n FROM clip_ids WHERE id=?", (v["id"],))["n"] == 1

def test_97_10_titles_without_latin_letters_and_long_titles(nm):
    t = mk(nm, "R", "உள்ளாட்சி தேர்தல்"); assert re.match(r"^\d{6}_S[A-Z0-9]+$", t["name_id"])
    long = mk(nm, "R", "HL " + "WORD " * 40); assert len(long["name_id"]) - 7 <= 100 and len(long["name_id"]) - 7 > 40

def test_97_11_legacy_setting_keeps_one_id_for_name_and_internal(tmp_path, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "legacy"); monkeypatch.setenv("CHECK_CHAR", "1"); s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; c = mk(s, "R", "Fire")
    assert c["name_id"] is None and re.match(r"^\d{8}_0001[A-Z]_FIRE$", c["display_id"]); assert s.call("GET", "/api/clips")[1]["clips"][0]["name_id"] == c["display_id"]
    d, num = c["display_id"].split("_")[:2]; assert s.svc("GET", "/svc/match?day=%s&seq=%d&version=1&chk=%s" % (d, int(num[:4]), num[4:]))[0] == 200
    assert s.call("POST", "/api/clips/%d/version" % c["id"])[1]["display_id"] == c["display_id"] + "_V2"

def test_97_12_the_watcher_reads_both_kinds_of_file_name():
    assert w.parse_name("111126_OPENING_MONTAGE.mp4") == ("NAME", "111126_OPENING_MONTAGE", 1, None)
    assert w.parse_name("111126_opening_montage_V2.mxf") == ("NAME", "111126_OPENING_MONTAGE_V2", 2, None)
    assert w.parse_name("20261111_1185G_OPENING_MONTAGE.mp4") == ("20261111", 1185, 1, "G") and w.parse_name("OPENING_MONTAGE.mp4") is None
    assert w.key_query(w.parse_name("111126_A_B.mp4")) == "name=111126_A_B" and w.key_query(("20261111", 1185, 1, "G")) == "day=20261111&seq=1185&version=1&chk=G"

def test_97_13_the_poller_matches_media_to_the_clip_name_and_old_ids_still_work():
    r = {"name_id": "111126_OPENING_MONTAGE", "display_id": "20261111_0001A_OPENING_MONTAGE", "version": 1}
    assert bp.rkey(r) == bp.media_key("111126_OPENING_MONTAGE.mxf") == bp.media_key("111126_opening_montage") and bp.media_key("111126_OPENING_MONTAGE_2.mxf") != bp.rkey(r)
    assert bp.rkey(dict(r, name_id="111126_OPENING_MONTAGE_V2", version=2)) == bp.media_key("111126_OPENING_MONTAGE_V2.mxf") == ("111126_OPENING_MONTAGE", 2)
    assert bp.rkey({"name_id": "20261111_0001A_X", "display_id": "20261111_0001A_X", "version": 1}) == bp.media_key("20261111_0001A_X_extra.mxf") == ("20261111_0001A", 1)
    assert bp.ignored("Opening Montage", ["OPENING MONTAGE"]) and bp.ignored("END MONTAGE 2", ["END MONTAGE"]) and not bp.ignored("HL OPENING MONTAGE", ["OPENING MONTAGE"])
    assert gw.ID_RE.match("111126_OPENING_MONTAGE") and gw.ID_RE.match("20261111_1185G_X") and not gw.ID_RE.match("OPENING_MONTAGE")

def test_97_14_montage_stories_get_an_id_but_the_tool_never_attaches_them(env, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); s, f, p = env; f.slugs = [slug(1, "OPENING MONTAGE", 1), slug(2, "HL FISHERMAN", 2)]; p.cycle(); rows = {r["slug"]: r for r in s.svc("GET", "/svc/clips")[1]}
    assert set(rows) == {"OPENING MONTAGE", "HL FISHERMAN"} and all(r["name_id"].count("_") >= 1 and r["name_id"][:6].isdigit() for r in rows.values())
    for r in rows.values(): s.svc("POST", "/svc/files", {"display_id": r["display_id"], "state": "ON_NITRO"})
    f.medias = [media(11, rows["OPENING MONTAGE"]["name_id"] + ".mxf"), media(12, rows["HL FISHERMAN"]["name_id"] + ".mxf")]
    out = p.cycle(); assert [o["did"] if "did" in o else o.get("display_id") for o in out] and len(out) == 1 and "HL_FISHERMAN" in str(out[0]).upper()

def test_97_15_the_server_reports_10_4_0(nm): assert nm.call("GET", "/api/config")[1]["version"] == "11.2"

def test_97_16_spaces_dashes_and_underscores_are_the_same_in_a_file_name():
    p = w.parse_name
    assert p("121126 HL TN GOVT ON EX JUDGE.mxf") == ("NAME", "121126_HL_TN_GOVT_ON_EX_JUDGE", 1, None)
    assert p("111126_HL CABINET APROVE FERTILIZER SUBSIDY 4 PM.mxf") == ("NAME", "111126_HL_CABINET_APROVE_FERTILIZER_SUBSIDY_4_PM", 1, None)
    assert p("121126_V_JUSTIN KRC - COLLECT.mxf") == ("NAME", "121126_V_JUSTIN_KRC_COLLECT", 1, None) and p("121126 FIRE V2.mxf")[2] == 2
    assert p("12112026_HL TNI MULLAI.mxf") is None, "an 8-digit date is not our ID"
    assert bp.media_key("111126_HL CABINET - PLAN 4 PM.mxf") == bp.clip_key("111126_HL_CABINET_PLAN_4_PM", 1) and bp.media_key("12112026_HL TNI.mxf") is None

def test_97_17_the_registry_finds_the_clip_by_a_name_written_with_spaces(nm):
    import urllib.parse as up
    c = mk(nm, "R", "HL Cabinet approves fertilizer subsidy"); typed = c["name_id"].replace("_", " ").lower() + ".mxf"
    assert nm.svc("GET", "/svc/match?name=" + up.quote(typed.rsplit(".", 1)[0]))[0] == 200

def test_97_18_only_the_day_folders_of_the_on_air_share_are_scanned(tmp_path, monkeypatch):
    import datetime as dt, time
    on = tmp_path / "ONAIR"; names = {"Nov-26/12-11-2026": "121126 HL X.mxf", "Nov-26/05-11-2026": "121126 HL X.mxf", "Nov-26/11-11-2026": "111126 HL Y.mxf", "10_Oct-26/10-10-2026": "121126 HL X.mxf"}
    for d, n in names.items(): (on / d).mkdir(parents=True); (on / d / n).write_bytes(b"x")
    noon = dt.datetime(2026, 11, 12, 12, 0).timestamp(); monkeypatch.setattr(w, "_wall", lambda: noon); monkeypatch.setattr(w, "NITRO", str(on))
    monkeypatch.setattr(w, "NITRO_DATE_PATH", ["%b-%y/%d-%m-%Y", "%m_%b-%y/%d-%m-%Y"]); monkeypatch.setattr(w, "NITRO_EXTS", (".mxf",))
    wanted = {("NAME", "121126_HL_X", 1), ("NAME", "111126_HL_Y", 1)}; f = w.scan_nitro(wanted)
    assert set(f) == wanted and f[("NAME", "121126_HL_X", 1)][0].endswith("Nov-26/12-11-2026/121126 HL X.mxf"), "today's and yesterday's folders only: not the 5th, not October"
    monkeypatch.setattr(w, "NITRO", str(tmp_path / "unmounted"))
    with pytest.raises(OSError): w.scan_nitro(wanted)
