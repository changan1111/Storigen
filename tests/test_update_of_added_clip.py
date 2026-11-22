"""VERSION_SUFFIX=on: Karth_V01_U01 is an UPDATE of the added clip Karth_V01 (its own chain beside Karth_Un): U01 replaces V01, U02 replaces U01.
The base chain (Karth_U01) and this chain never touch each other, and the next-number rule holds in each."""
import datetime as dt
from test_server import Srv
from autoid_lite.blaze.attach import AttachMixin as Attach
from autoid_lite.ids import kind_of, vlabel, un_of

def test_chain_numbers_and_labels():
    assert kind_of(10101) == "U" and vlabel(10101) == "V01_U01" and vlabel(10215) == "V02_U15" and un_of(10103) == 3 and un_of(1003) == 3 and vlabel(1001) == "U01" and vlabel(2001) == "V01"

def test_the_registry_makes_the_chain_clips_in_order(tmp_path, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("VERSION_SUFFIX", "on")
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    s.call("POST", "/api/manual", {"rundown": "14:00 Bulletin", "story": "Karth"}); d = dt.date.today().strftime("%d%m%y"); m = lambda n: s.svc("GET", "/svc/match?name=%s_KARTH%s" % (d, n))[0]
    assert m("_V01_U01") == 404, "no V01 clip yet: nothing to update"
    assert m("_V01") == 200 and m("_V01_U01") == 200 and m("_U01") == 200, "the base chain has its own U01"
    assert m("_V01_U03") == 404 and m("_V01_U02") == 200 and m("_U02") == 200
    assert m("_V01_U100") == 404 and m("_V02_U01") == 404, "no V02 yet"
    with s.app.db.tx() as cur: got = sorted((x["name_id"], x["version"]) for x in cur.q("SELECT name_id, version FROM clip_ids"))
    assert got == sorted([(d + "_KARTH", 1), (d + "_KARTH_V01", 2001), (d + "_KARTH_V01_U01", 10101), (d + "_KARTH_V01_U02", 10102), (d + "_KARTH_U01", 1001), (d + "_KARTH_U02", 1002)])

def test_the_attach_step_replaces_the_right_clip(monkeypatch):
    monkeypatch.setenv("VERSION_SUFFIX", "on"); d = dt.date.today().strftime("%d%m%y")
    row = lambda i, t: {"id": i, "title": t, "mos": "m" + i}
    story = [row("1", d + "_KARTH.mxf"), row("2", d + "_KARTH_V01.mxf"), row("3", d + "_KARTH_V01_U01.mxf")]
    older = lambda name, ver, rows: [x["id"] for x in Attach.older_versions(None, {"name_id": name, "display_id": name, "version": ver}, {"rows": rows})]
    assert older(d + "_KARTH_U01", 1001, story) == ["1"], "the base chain replaces the base clip only"
    assert older(d + "_KARTH_V01_U01", 10101, story[:2]) == ["2"], "V01_U01 replaces the added clip V01"
    assert older(d + "_KARTH_V01_U02", 10102, story) == ["3"], "V01_U02 replaces V01_U01, nothing else"
    assert older(d + "_KARTH_V01", 2001, story) == [], "an added clip replaces nothing"
