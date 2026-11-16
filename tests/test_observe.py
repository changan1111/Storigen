"""Observe mode: Playout inbox -> (external job converts, hides the original) -> MXF on Nitro. The watcher only watches; it never touches a file."""
import os, pathlib, sys, urllib.error
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "autoid_lite"))
import watcher

DID = "20261103_0007_STORY"; SRC = DID + ".mov"; MXF = DID + ".mxf"

class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t

@pytest.fixture
def env(tmp_path, monkeypatch):
    inbox, nitro = tmp_path / "INBOX", tmp_path / "ONAIR"
    for d in ("NEWS", "PROMO"): (inbox / d).mkdir(parents=True)
    (nitro / "20261103" / "NEWS").mkdir(parents=True)
    monkeypatch.setattr(watcher, "WATCH_MODE", "observe"); monkeypatch.setattr(watcher, "EXPORTS", str(inbox)); monkeypatch.setattr(watcher, "NITRO", str(nitro))
    monkeypatch.setattr(watcher, "INBOX_DIRS", ["NEWS", "PROMO"]); monkeypatch.setattr(watcher, "STATE_FILE", str(tmp_path / "state" / "s.json"))
    monkeypatch.setattr(watcher, "STABLE", 30); monkeypatch.setattr(watcher, "DONE_WAIT", 900); monkeypatch.setattr(watcher, "STUCK_SECS", 1800)
    monkeypatch.setattr(watcher, "NITRO_SCAN_EVERY", 0); monkeypatch.setattr(watcher, "REQUIRE_NET_FS", False)
    clock = Clock(); monkeypatch.setattr(watcher, "_now", clock); monkeypatch.setattr(watcher, "_wall", clock)
    watcher._OBS.clear(); watcher._ALERTED.clear(); watcher._LAST_SCAN[:] = [-1e18, {}]
    reports, alerts, known = [], [], {"20261103_0007": DID}
    def api(path, payload=None):
        if path.startswith("/svc/match"):
            q = dict(x.split("=") for x in path.split("?")[1].split("&")); key = "%s_%04d" % (q["day"], int(q["seq"]))
            if key not in known: raise urllib.error.HTTPError(path, 404, "nf", {}, None)
            return {"display_id": known[key]}
        reports.append((payload["display_id"], payload["state"], payload)); return {"ok": True}
    monkeypatch.setattr(watcher, "api", api); monkeypatch.setattr(watcher, "alert", lambda t: alerts.append(t))
    (nitro_file := nitro / "20261103" / "NEWS" / MXF)
    return type("E", (), dict(inbox=inbox, nitro=nitro, mxf=nitro_file, reports=reports, alerts=alerts, clock=clock, state={}, tmp=tmp_path))

def tick(env, advance=0): env.clock.t += advance; watcher.observe_tick(env.state)
def states(env): return [r[1] for r in env.reports]

def test_file_in_inbox_reports_exporting_once_and_is_never_touched(env):
    f = env.inbox / "NEWS" / SRC; f.write_bytes(b"x" * 1000)
    tick(env); assert states(env) == []                      # just appeared, may still be growing
    tick(env, 31); tick(env, 5); assert states(env) == ["EXPORTING"]
    assert f.exists() and f.read_bytes() == b"x" * 1000 and not list(env.nitro.rglob("*.mxf"))     # nothing copied, moved or changed

def test_disappear_plus_mxf_on_nitro_means_on_nitro(env):
    f = env.inbox / "NEWS" / SRC; f.write_bytes(b"x"); tick(env); tick(env, 31)
    f.unlink(); env.mxf.write_bytes(b"m" * 500)
    tick(env, 5); assert "ON_NITRO" not in states(env)       # Nitro file just seen: wait until its size is stable
    tick(env, 31); assert states(env)[-1] == "ON_NITRO"
    last = env.reports[-1][2]; assert last["nitro_path"] == str(env.mxf) and last["size"] == 500 and env.state == {}

def test_growing_mxf_is_not_reported_until_it_stops_growing(env):
    f = env.inbox / "NEWS" / SRC; f.write_bytes(b"x"); tick(env); f.unlink(); env.mxf.write_bytes(b"1"); tick(env, 5)
    env.mxf.write_bytes(b"12"); os.utime(env.mxf, (1, 2)); tick(env, 31); assert "ON_NITRO" not in states(env)
    tick(env, 31); assert states(env)[-1] == "ON_NITRO"

def test_hidden_dot_file_counts_as_disappeared(env):
    f = env.inbox / "NEWS" / SRC; f.write_bytes(b"x"); tick(env); f.rename(f.with_name("." + SRC)); env.mxf.write_bytes(b"m")
    tick(env, 5); tick(env, 31); assert states(env)[-1] == "ON_NITRO"

def test_disappeared_without_mxf_goes_to_desk_after_wait_then_recovers_if_mxf_arrives(env):
    f = env.inbox / "NEWS" / SRC; f.write_bytes(b"x"); tick(env); f.unlink()
    tick(env, 60); assert states(env) == [] and not env.alerts
    tick(env, 901); assert states(env) == ["NEEDS_DESK"] and len(env.alerts) == 1
    tick(env, 60); assert states(env) == ["NEEDS_DESK"] and len(env.alerts) == 1        # told once
    env.mxf.write_bytes(b"m"); tick(env, 5); tick(env, 31); assert states(env)[-1] == "ON_NITRO"

def test_listing_error_never_looks_like_everything_finished(env):
    (env.inbox / "NEWS" / SRC).write_bytes(b"x"); tick(env)
    os.rename(env.inbox / "NEWS", env.inbox / "NEWS.gone")
    with pytest.raises(OSError): tick(env, 5)
    assert list(env.state.values())[0]["gone_at"] is None and "ON_NITRO" not in states(env)

def test_wrong_seq_on_nitro_is_not_matched(env):
    f = env.inbox / "NEWS" / SRC; f.write_bytes(b"x"); tick(env); f.unlink()
    (env.nitro / "20261103" / "NEWS" / "20261103_0008_OTHER.mxf").write_bytes(b"m"); tick(env, 5); tick(env, 31)
    assert "ON_NITRO" not in states(env)

def test_name_without_id_and_unknown_id_alert_but_do_not_report(env):
    (env.inbox / "PROMO" / "holiday_promo.mov").write_bytes(b"x"); (env.inbox / "NEWS" / "20261103_0099_X.mov").write_bytes(b"x")
    tick(env); tick(env, 31)
    assert any("no ID" in a for a in env.alerts) and any("not in the registry" in a for a in env.alerts) and states(env) == []

def test_file_stuck_in_inbox_alerts_once(env):
    (env.inbox / "NEWS" / SRC).write_bytes(b"x"); tick(env); tick(env, 1801); tick(env, 60)
    assert sum("conversion may be failing" in a for a in env.alerts) == 1

def test_registry_down_at_report_time_keeps_waiting(env, monkeypatch):
    f = env.inbox / "NEWS" / SRC; f.write_bytes(b"x"); tick(env); tick(env, 31); f.unlink(); env.mxf.write_bytes(b"m"); tick(env, 5)
    real = watcher.api
    def down(path, payload=None): raise urllib.error.URLError("down")
    monkeypatch.setattr(watcher, "api", down); tick(env, 31); assert env.state and "ON_NITRO" not in states(env)
    monkeypatch.setattr(watcher, "api", real); tick(env, 5); assert states(env)[-1] == "ON_NITRO" and env.state == {}

def test_state_survives_a_restart(env):
    f = env.inbox / "NEWS" / SRC; f.write_bytes(b"x"); tick(env); watcher.save_state(env.state)
    env.state = watcher.load_state(); assert list(env.state.values())[0]["did"] == DID
    f.unlink(); env.mxf.write_bytes(b"m"); tick(env, 5); tick(env, 31); assert states(env)[-1] == "ON_NITRO"

def test_storage_check_in_observe_mode_needs_subfolders_and_no_write_access_to_nitro(env, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_FILE", str(env.tmp / "state" / "s.json")); (env.tmp / "state").mkdir()
    assert watcher.storage_problem() is None
    (env.inbox / "PROMO").rmdir(); assert "PROMO" in watcher.storage_problem()
