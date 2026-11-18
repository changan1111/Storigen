"""v9.7.5: the four-step strip EXPORT -> ON AIR -> NITRO -> ATTACHED. Each step is green only when it was recorded; dry mode never attaches."""
import re, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from test_server import Srv, sid      # reuse the server fixtures

def test_ui_has_the_four_steps():
    h = (pathlib.Path(__file__).resolve().parents[1] / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    for t in ('"IN EXPORT"', '"ON AIR"', '"NITRO"', '"ATTACHED"', "export_folder"): assert t in h

def test_dry_poller_cannot_attach():
    b = pathlib.Path(__file__).resolve().parents[1] / "autoid_lite" / "blaze"; p = "".join((b / f).read_text(encoding="utf-8") for f in ("client.py", "attach.py"))      # the engine moved from tools/blaze_poll.py into the package: scan the same code, in the same order
    assert 'if self.c.attach != "live" and not self.quick_ok(story_id): raise ForbiddenCall' in p and 'if self.c.attach != "live": raise ForbiddenCall' not in p.split("def attach(")[1].split("def delete_clip")[0]      # v9.13: the only way past it is BlazeClient.quick(), used by a confirmed Quick test
    assert p.count("with self.b.quick(") == 1 and p.count("quick=qa)") == 2, "quick() is entered in one place only (live_attach); it is reached only for a clip whose Quick test was confirmed: the plain attach and, since v10.5.0, the replace of a _Un clip"
    assert 'removing a clip is only allowed with BLAZE_ATTACH=live' in p and p.count("quick=quick, show=show)") == 1, "v10.5.0: the delete of a replace has the same wall as the attach"

def _clip(s):
    s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "7", "rundown_name": "NOON", "stories": [{"blaze_story_id": "501", "slug": "FLOOD", "title": "Flood"}]})
    return s.call("GET", "/api/clips?per_page=50")[1]["clips"][0]

def test_strip_turns_green_step_by_step(sid):
    c = _clip(sid); did = c["display_id"]
    assert c["stages"] == {"export": False, "export_folder": None, "onair": False, "nitro": False, "attached": False}
    sid.svc("POST", "/svc/files", {"display_id": did, "state": "EXPORTING", "nas_path": "/Volumes/Playout/INBOX/NEWS/x.mov"})
    st = sid.call("GET", "/api/clips?per_page=50")[1]["clips"][0]["stages"]; assert st["export"] and st["export_folder"] == "NEWS" and not st["onair"]
    sid.svc("POST", "/svc/files", {"display_id": did, "state": "ON_NITRO", "nas_path": "/Volumes/Playout/INBOX/NEWS/x.mov", "nitro_path": "/Volumes/Nitro/ONAIR/x.mxf"})
    st = sid.call("GET", "/api/clips?per_page=50")[1]["clips"][0]["stages"]; assert st["onair"] and not st["nitro"] and not st["attached"]
    assert sid.svc("POST", "/svc/media", {"display_id": did, "media_id": "9911"})[0] == 200
    st = sid.call("GET", "/api/clips?per_page=50")[1]["clips"][0]["stages"]; assert st["nitro"] and not st["attached"]      # media found, nothing attached (dry)
    assert sid.svc("POST", "/svc/media", {"display_id": "nope", "media_id": "1"})[0] == 404

def test_attached_only_when_attached(sid):
    c = _clip(sid); did = c["display_id"]
    sid.svc("POST", "/svc/files", {"display_id": did, "state": "ON_NITRO", "nitro_path": "/n/x.mxf"})
    sid.svc("POST", "/svc/media", {"display_id": did, "media_id": "5"})
    assert not sid.call("GET", "/api/clips?per_page=50")[1]["clips"][0]["stages"]["attached"]
    assert sid.call("POST", "/api/clips/%d/attached" % c["id"])[0] == 200
    assert sid.call("GET", "/api/clips?per_page=50")[1]["clips"][0]["stages"]["attached"]
