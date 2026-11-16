import datetime as dt, sys, pathlib
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "autoid_lite"))
from autoid_lite.ids import make_slug, broadcast_day, display_id, check_char
from autoid_lite.security import access_state, PERMS
import gateway, watcher, os
os.environ['CHECK_CHAR']='0'


def test_slug_and_ids():
    assert make_slug("Vijay scheme: launch!") == "VIJAY_SCHEME_LAUNCH"
    assert make_slug("") == "STORY"
    d = dt.date(2026, 10, 20)
    assert display_id(d, 42, "Vijay scheme") == "20261020_0042_VIJAY_SCHEME"
    assert display_id(d, 42, "Vijay scheme", 2) == "20261020_0042_VIJAY_SCHEME_V2"

def test_broadcast_day_rolls_at_0500():
    assert broadcast_day(dt.datetime(2026, 10, 21, 2, 0), "05:00") == dt.date(2026, 10, 20)
    assert broadcast_day(dt.datetime(2026, 10, 21, 5, 1), "05:00") == dt.date(2026, 10, 21)

def test_filename_matching_ignores_slug_typos():
    assert watcher.parse_name("20261020_0042_VIJAY_SCHEMEE.mov") == ("20261020", 42, 1, None)
    assert watcher.parse_name("20261020_0042_X_V3.mp4") == ("20261020", 42, 3, None)
    assert watcher.parse_name("20261020_0042.mov") == ("20261020", 42, 1, None)
    assert watcher.parse_name("final_cut.mov") is None

HDR = "<mosID>M</mosID><ncsID>N</ncsID><messageID>7</messageID>"
def test_mos_rocreate_and_ack():
    xml = "<mos>%s<roCreate><roID>RO1</roID><roSlug>Eve</roSlug><story><storyID>S1</storyID><storySlug>A</storySlug></story></roCreate></mos>" % HDR
    hdr, body = gateway.parse_mos(xml)
    acts = gateway.actions_for(body)
    assert acts == [("/svc/rundowns/sync", {"blaze_rundown_id": "RO1", "rundown_name": "Eve", "stories": [{"blaze_story_id": "S1", "slug": "A"}]})]
    assert "<roStatus>OK</roStatus>" in gateway.reply(hdr, gateway.ro_ack("RO1"))

def test_story_replace_with_new_id_renames():
    xml = "<mos>%s<roStoryReplace><roID>R</roID><storyID>S1</storyID><story><storyID>S9</storyID><storySlug>B</storySlug></story></roStoryReplace></mos>" % HDR
    acts = gateway.actions_for(gateway.parse_mos(xml)[1])
    assert acts[0][0] == "/svc/stories/rename" and acts[1][0] == "/svc/stories"

def test_heartbeat_reply():
    r = gateway.handle("<mos>%s<heartbeat><time>x</time></heartbeat></mos>" % HDR)
    assert "<heartbeat>" in r and "<messageID>7</messageID>" in r

def test_check_char_catches_typos_and_parses():
    d = dt.date(2026, 10, 20); c = check_char(d, 42)
    assert c != check_char(d, 43) and c != check_char(d, 24) and c != check_char(d, 52)
    assert display_id(d, 42, "X", check=True) == "20261020_0042%s_X" % c
    assert watcher.parse_name("20261020_0042%s_X.mov" % c) == ("20261020", 42, 1, c)

def test_access_rule_smoke():
    t = dt.date(2026, 11, 3); assert access_state({"role": "editor", "active": True, "valid_upto": "2026-11-03"}, t)[0] and not access_state({"role": "editor", "active": True, "valid_upto": "2026-11-02"}, t)[0]


# ---------- registry acknowledgement is mandatory before archiving ----------
import urllib.error, pytest, socket, threading

def _setup_watcher(tmp_path, monkeypatch, calls, fail_on=None):
    for n in ("exports", "nitro", "archive", "quar"): (tmp_path / n).mkdir()
    monkeypatch.setattr(watcher, "EXPORTS", str(tmp_path / "exports")); monkeypatch.setattr(watcher, "NITRO", str(tmp_path / "nitro"))
    monkeypatch.setattr(watcher, "ARCH", str(tmp_path / "archive")); monkeypatch.setattr(watcher, "QUAR", str(tmp_path / "quar"))
    monkeypatch.setattr(watcher, "NEED_PROBE", False); monkeypatch.setattr(watcher, "LOCK_DIR", str(tmp_path / "locks"))
    watcher.MINE.clear(); watcher._OBS.clear(); watcher.WATCH_MODE = 'move'
    src = tmp_path / "exports" / "20261020_0042_X.mov"; src.write_bytes(b"clip-bytes" * 100)
    def fake_api(path, payload=None):
        if path.startswith("/svc/match"): return {"display_id": "20261020_0042_X"}
        calls.append(payload["state"])
        if payload["state"] == fail_on: raise urllib.error.URLError("registry down")
        return {"ok": True}
    monkeypatch.setattr(watcher, "api", fake_api); return src

def test_registry_down_keeps_source_then_recovers(tmp_path, monkeypatch):
    calls = []; src = _setup_watcher(tmp_path, monkeypatch, calls, fail_on="ON_NITRO")
    with pytest.raises(watcher.RegistryUnavailable): watcher.process(str(src))
    assert src.exists() and not list((tmp_path / "archive").iterdir())          # NOT archived without the acknowledgement
    assert (tmp_path / "nitro" / src.name).exists()                              # copied, so recovery is only a re-report
    monkeypatch.setattr(watcher, "api", lambda p, d=None: {"display_id": "20261020_0042_X"} if p.startswith("/svc/match") else {"ok": True})
    watcher.process(str(src))                                                    # next poll: idempotent, acknowledged, archived
    assert not src.exists() and len(list((tmp_path / "archive").iterdir())) == 1

def test_verified_report_failure_stops_before_copy(tmp_path, monkeypatch):
    calls = []; src = _setup_watcher(tmp_path, monkeypatch, calls, fail_on="VERIFIED")
    with pytest.raises(watcher.RegistryUnavailable): watcher.process(str(src))
    assert src.exists() and not (tmp_path / "nitro" / src.name).exists()

# ---------- gateway: read-back confirmation from Blaze ----------
def test_item_in_story_becomes_confirmation_call():
    xml = ("<mos>%s<roStoryReplace><roID>R1</roID><storyID>S1</storyID><story><storyID>S1</storyID><storySlug>A</storySlug>"
           "<item><itemID>1</itemID><objID>20261020_0042K_X</objID></item><item><itemID>2</itemID><objID>OTHER_CLIP</objID></item></story></roStoryReplace></mos>") % HDR
    body = gateway.parse_mos(xml)[1]
    assert gateway.confirmations(body) == [("/svc/attach/confirm", {"display_id": "20261020_0042K_X", "blaze_rundown_id": "R1", "blaze_story_id": "S1", "source": "mos_item"})]
    xml2 = "<mos>%s<roItemInsert><roID>R1</roID><storyID>S2</storyID><itemID>0</itemID><item><itemID>5</itemID><objID>20261020_0007_Y</objID></item></roItemInsert></mos>" % HDR
    assert gateway.confirmations(gateway.parse_mos(xml2)[1])[0][1]["blaze_story_id"] == "S2"
