"""v9.13.1: the poller reads autoid.env once, at start. When the file is edited later the dashboard says the running poller still uses the old values."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_blaze_poll import bp, env, clips
from autoid_lite.blaze import envcheck

def test_differences_name_the_setting_the_old_and_the_new_value():
    snap = envcheck.snapshot({"BLAZE_ATTACH": "dry", "QUICKTEST_STORY_ID": "731613"})
    assert envcheck.differences(snap, {"BLAZE_ATTACH": "dry", "QUICKTEST_STORY_ID": "731613"}) == []
    d = envcheck.differences(snap, {"BLAZE_ATTACH": "live", "QUICKTEST_STORY_ID": "731613"}); assert len(d) == 1 and "BLAZE_ATTACH" in d[0] and "dry" in d[0] and "live" in d[0]
    d = envcheck.differences(snap, {"BLAZE_ATTACH": "dry"}); assert len(d) == 1 and "QUICKTEST_STORY_ID" in d[0] and "(not set)" in d[0]

def problems(s): return s.call("GET", "/api/status")[1]["problems"]

def test_the_dashboard_warns_until_the_poller_is_restarted(env, tmp_path, monkeypatch):
    s, f, p = env; assert s.login()[0] == 200
    file = tmp_path / "autoid.env"; monkeypatch.setenv("AUTOID_ENV", str(file))
    same = "\n".join("%s=%s" % kv for kv in p.c.env_seen.items()) + "\n"
    file.write_text(same, encoding="utf-8"); p.drift_at = 0; p.cycle()
    assert not any("autoid.env was changed" in x for x in problems(s)), "file and poller agree: no warning"
    file.write_text(same.replace("BLAZE_ATTACH=", "BLAZE_ATTACH=live", 1), encoding="utf-8"); p.drift_at = 0; p.cycle()
    w = [x for x in problems(s) if "autoid.env was changed" in x]; assert len(w) == 1 and "BLAZE_ATTACH" in w[0] and "Restart" in w[0]
    file.write_text(same, encoding="utf-8"); p.drift_at = 0; p.cycle()
    assert not any("autoid.env was changed" in x for x in problems(s)), "edited back: the warning goes away"

def test_a_poller_without_an_env_file_never_warns(env, tmp_path, monkeypatch):
    s, f, p = env; assert s.login()[0] == 200; monkeypatch.setenv("AUTOID_ENV", str(tmp_path / "missing.env")); p.drift_at = 0; p.cycle()
    assert not any("autoid.env was changed" in x for x in problems(s))
