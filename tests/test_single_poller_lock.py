"""v9.13.1: only one `blaze_poll.py run` at a time (a second one logs in as the same Blaze user and can replace the first one's session)."""
import os, subprocess, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_blaze_poll import bp
from autoid_lite.blaze import lock as plock

def test_a_second_poller_is_refused_and_told_who_holds_the_lock(tmp_path):
    path = tmp_path / "blaze_poll.lock"; plock.acquire(path)
    try: plock.acquire(path); raised = None
    except plock.AlreadyRunning as e: raised = e
    assert raised is not None and "pid %d" % os.getpid() in str(raised), "the message names the running poller"

def test_the_run_command_stops_with_a_clear_message_before_it_logs_in(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); monkeypatch.delenv("BLAZE_POLL_NO_LOCK", raising=False); plock.acquire(tmp_path / "blaze_poll.lock")
    try: bp.main(["run"]); msg = None
    except SystemExit as e: msg = str(e)
    assert msg and "already running" in msg and "Only one poller" in msg

def test_the_lock_is_free_again_when_the_process_ends(tmp_path):
    path = tmp_path / "blaze_poll.lock"; root = str(pathlib.Path(__file__).resolve().parents[1])
    code = "import sys; sys.path.insert(0, %r); from autoid_lite.blaze import lock; lock.acquire(%r)" % (root, str(path))
    assert subprocess.run([sys.executable, "-c", code], timeout=30).returncode == 0                  # that process held it and exited (even a crash frees it)
    plock.acquire(path)

def test_other_commands_do_not_take_the_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); plock.acquire(tmp_path / "blaze_poll.lock")
    try: bp.main(["live"]); msg = ""
    except SystemExit as e: msg = str(e)
    assert "already running" not in msg, "read-only commands (live, report, map ...) still work while the poller runs"
