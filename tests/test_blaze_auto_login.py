"""v9.7.3: the poller logs in to Blaze by itself (POST /DataService/sessions, as captured) and keeps the new session. Against the fake Blaze: nothing here touches a real server."""
import sys, pathlib, urllib.parse
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "tests"))
from test_blaze_poll import Fake, bp, slug
from test_server import Srv

HASH = "Zm9vYmFyYmF6+/ZvbyBiYXI="          # made up, same shape as the page's value: base64 with + / =
EXPIRED = bp.SessionExpired("the session cookie is not valid any more")

def cfg_for(f, s, tmp_path, **extra):
    base = {"BLAZE_URL": "http://127.0.0.1:%d" % f.port, "BLAZE_SESSION_ID": "OLD", "BLAZE_USERNAME": "u", "BLAZE_PASSWORD_HASH": HASH, "BLAZE_SHOW_IDS": "34427",
            "WEB_PORT": str(s.port), "SERVICE_API_KEY": "k" * 20, "BLAZE_LEDGER": str(tmp_path / "ledger.db"), "BLAZE_REPORT_DIR": str(tmp_path / "reports"),
            "BLAZE_MEDIA_RETRY_SECS": "0", "BLAZE_INFO_SECS": "0"}
    base.update(extra); return bp.Cfg({k: v for k, v in base.items() if v is not None})

@pytest.fixture
def lenv(tmp_path, monkeypatch):
    envfile = tmp_path / "autoid.env"; monkeypatch.setenv("AUTOID_ENV", str(envfile))
    envfile.write_text("# keep me\nOTHER_SETTING=1\nBLAZE_SESSION_ID=OLD\nBLAZE_USERNAME=u\nBLAZE_PASSWORD_HASH=%s\n# and me\n" % HASH, encoding="utf-8")
    s = Srv(tmp_path, "story_id"); f = Fake(); return s, f, bp.Poller(cfg_for(f, s, tmp_path)), envfile

def test_login_posts_the_page_form_and_returns_the_session(lenv):
    s, f, p, _ = lenv; assert p.b.login() == "NEWSID"
    form = f.logins[0]; assert form["username"] == "u" and form["password"] == HASH and form["_"].isdigit()       # the server sees the raw hash: + / = survived the encoding

def test_a_percent_encoded_hash_copied_from_the_capture_is_accepted(tmp_path):
    c = bp.Cfg({"BLAZE_USERNAME": "u", "BLAZE_PASSWORD_HASH": urllib.parse.quote(HASH, safe="")}); assert c.pw == HASH and c.autologin

def test_the_session_is_read_from_set_cookie_or_from_location(lenv):
    s, f, p, _ = lenv
    for mode in ("cookie", "location"): f.login_mode = mode; assert p.b.login() == "NEWSID"

def test_a_refused_login_or_one_without_a_session_is_a_clear_failure(lenv):
    s, f, p, _ = lenv
    f.login_mode = "refuse"
    with pytest.raises(bp.LoginFailed, match="401"): p.b.login()
    f.login_mode = "none"
    with pytest.raises(bp.LoginFailed, match="no session ID"): p.b.login()

def test_expired_session_is_replaced_by_a_login_and_the_next_round_works(lenv):
    s, f, p, envfile = lenv; f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); f.expired = True
    with pytest.raises(bp.SessionExpired): p.cycle()
    assert p.session_problem(EXPIRED, False) is False                           # logged in again: not a problem any more
    assert p.c.sid == "NEWSID" and len(f.logins) == 1
    f.cookies.clear(); p.cycle(); assert f.cookies and all("sessionId=NEWSID" in c for c in f.cookies)
    txt = envfile.read_text(encoding="utf-8")
    assert txt.count("BLAZE_SESSION_ID=") == 1 and "BLAZE_SESSION_ID=NEWSID" in txt and "# keep me" in txt and "# and me" in txt and "OTHER_SETTING=1" in txt and "BLAZE_PASSWORD_HASH=" + HASH in txt

def test_the_call_that_failed_is_not_repeated_by_the_login(lenv):
    s, f, p, _ = lenv; f.slugs = [slug(1, "A", 1)]; p.cycle(); f.expired = True; before = len(f.log)
    p.session_problem(EXPIRED, False); assert [x for x in f.log[before:] if x[0] != "POST"] == [] and len(f.logins) == 1       # only the login itself was sent

def test_a_refused_login_stops_after_three_tries_so_the_account_is_not_locked(lenv):
    s, f, p, _ = lenv; f.login_mode = "refuse"
    for _ in range(6): p.login_at = 0; assert p.session_problem(EXPIRED, False) is True        # login_at = 0 skips the pause between tries
    assert len(f.logins) == 3 and p.login_fails == 3

def test_there_is_a_pause_between_login_tries(lenv):
    s, f, p, _ = lenv; f.login_mode = "refuse"
    p.session_problem(EXPIRED, False); p.session_problem(EXPIRED, False); p.session_problem(EXPIRED, False); assert len(f.logins) == 1

def test_a_fresh_cookie_in_autoid_env_wins_over_a_login_and_resets_the_count(lenv):
    s, f, p, envfile = lenv; p.login_fails = 2
    envfile.write_text(envfile.read_text(encoding="utf-8").replace("BLAZE_SESSION_ID=OLD", "BLAZE_SESSION_ID=FROMFILE"), encoding="utf-8")
    assert p.session_problem(EXPIRED, False) is False and p.c.sid == "FROMFILE" and not f.logins and p.login_fails == 0

def test_without_a_password_hash_nothing_changes(tmp_path):
    s = Srv(tmp_path, "story_id"); f = Fake(); p = bp.Poller(cfg_for(f, s, tmp_path, BLAZE_PASSWORD_HASH=None))
    assert not p.c.autologin and p.session_problem(EXPIRED, False) is True and not f.logins

def test_autologin_can_be_switched_off(tmp_path):
    s = Srv(tmp_path, "story_id"); f = Fake(); p = bp.Poller(cfg_for(f, s, tmp_path, BLAZE_AUTOLOGIN="0"))
    assert not p.c.autologin and p.session_problem(EXPIRED, False) is True and not f.logins

def test_start_without_a_cookie_logs_in_first(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOID_ENV", str(tmp_path / "autoid.env")); s = Srv(tmp_path, "story_id"); f = Fake()
    c = cfg_for(f, s, tmp_path, BLAZE_SESSION_ID=None); assert c.sid == "" and bp.ensure_session(c, bp.Blaze(c)) is True and c.sid == "NEWSID"
    assert "BLAZE_SESSION_ID=NEWSID" in (tmp_path / "autoid.env").read_text(encoding="utf-8")
    c2 = cfg_for(f, s, tmp_path, BLAZE_SESSION_ID=None, BLAZE_PASSWORD_HASH=None); assert bp.ensure_session(c2, bp.Blaze(c2)) is False

def test_neither_the_hash_nor_the_whole_session_is_ever_printed(lenv, capsys):
    s, f, p, _ = lenv; f.login_mode = "refuse"; p.session_problem(EXPIRED, False)              # a failed login first ...
    f.login_mode = "ok"; p.login_at = 0; p.session_problem(EXPIRED, False)                      # ... then a good one
    out = capsys.readouterr(); text = out.out + out.err
    assert "LOGIN FAILED" in text and "logged in to Blaze again" in text and HASH not in text and urllib.parse.quote(HASH, safe="") not in text and "NEWSID" not in text and "WSID" in text

def test_the_login_is_the_only_new_write_the_boundary_allows():
    bp.check_call("POST", "/DataService/sessions")
    for m, path in (("POST", "/DataService/shows"), ("DELETE", "/DataService/sessions/abc"), ("POST", "/DataService/sessions/abc"), ("PUT", "/DataService/stories/5")):
        with pytest.raises(bp.ForbiddenCall): bp.check_call(m, path)

def test_a_read_only_one_off_command_logs_in_and_runs_again(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUTOID_ENV", str(tmp_path / "autoid.env")); f = Fake(); f.expired = True
    for k, v in {"BLAZE_URL": "http://127.0.0.1:%d" % f.port, "BLAZE_SESSION_ID": "OLD", "BLAZE_USERNAME": "u", "BLAZE_PASSWORD_HASH": HASH, "BLAZE_LEDGER": str(tmp_path / "l.db"), "BLAZE_REPORT_DIR": str(tmp_path / "r")}.items(): monkeypatch.setenv(k, v)
    assert bp.main(["media"]) == 0 and len(f.logins) == 1 and "logged in to Blaze again" in capsys.readouterr().out

def test_a_command_that_can_write_never_logs_in_and_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOID_ENV", str(tmp_path / "autoid.env")); f = Fake()
    for k, v in {"BLAZE_URL": "http://127.0.0.1:%d" % f.port, "BLAZE_SESSION_ID": "OLD", "BLAZE_USERNAME": "u", "BLAZE_PASSWORD_HASH": HASH, "BLAZE_SHOW_IDS": "34427", "BLAZE_LEDGER": str(tmp_path / "l.db"), "BLAZE_REPORT_DIR": str(tmp_path / "r"), "SERVICE_API_KEY": "k" * 20, "WEB_PORT": "1"}.items(): monkeypatch.setenv(k, v)
    def boom(self): raise bp.SessionExpired("expired in the middle of a round that may have been writing")
    monkeypatch.setattr(bp.Poller, "cycle", boom)
    with pytest.raises(SystemExit, match="PROBLEM"): bp.main(["once"])
    assert not f.logins                                                                         # `once` can attach: it is never run twice behind the user's back
