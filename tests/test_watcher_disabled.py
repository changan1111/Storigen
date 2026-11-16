"""v9.12: WATCHER_ENABLED=0 = no Playout / Nitro folders needed. No watcher is started, no red 'NAS or Nitro folder not reachable', the chips show NITRO and ATTACHED only."""
import sys, pathlib, importlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from test_server import Srv

def test_912_01_default_still_starts_the_watcher(monkeypatch, tmp_path):
    monkeypatch.delenv("WATCHER_ENABLED", raising=False); import autoid; names = [n for n, _ in autoid.child_specs()]
    assert "watcher" in names
    s = Srv(tmp_path, "story_id"); assert s.login()[0] == 200 and s.call("GET", "/api/config")[1]["watcher_enabled"] is True

def test_912_02_switched_off_no_watcher_no_red_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCHER_ENABLED", "0"); import autoid; assert "watcher" not in [n for n, _ in autoid.child_specs()]
    s = Srv(tmp_path, "story_id", {"WATCHER_ENABLED": "0"}); assert s.login()[0] == 200 and s.call("GET", "/api/config")[1]["watcher_enabled"] is False
    s.svc("POST", "/svc/heartbeat", {"component": "watcher", "detail": {"nas_ok": False, "problem": "Nitro folder is missing"}})       # an old heartbeat from before the switch
    assert s.call("GET", "/api/status")[1]["problems"] == []

def test_912_03_dashboard_hides_the_two_folder_steps_when_off():
    h = (pathlib.Path(__file__).resolve().parent.parent / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    assert "cfg.watcher_enabled===false" in h
