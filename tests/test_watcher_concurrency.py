"""Claims, stale-lock handling, partial-copy cleanup, and crash/restart during a copy. All real files, real processes for the kill test."""
import hashlib, json, os, pathlib, subprocess, sys, textwrap, threading, time, urllib.error
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "autoid_lite"))
import watcher

NAME = "20261020_0042_X.mov"; DID = "20261020_0042_X"; DATA = b"clip-bytes-" * 20000      # ~220 KB

class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t

@pytest.fixture
def env(tmp_path, monkeypatch):
    for n in ("exports", "nitro", "archive", "quar", "locks"): (tmp_path / n).mkdir()
    for k, n in (("EXPORTS", "exports"), ("NITRO", "nitro"), ("ARCH", "archive"), ("QUAR", "quar"), ("LOCK_DIR", "locks")): monkeypatch.setattr(watcher, k, str(tmp_path / n))
    monkeypatch.setattr(watcher, "NEED_PROBE", False); monkeypatch.setattr(watcher, "CHUNK", 4096); monkeypatch.setattr(watcher, "COPY_HOOK", None)
    clock = Clock(); monkeypatch.setattr(watcher, "_now", clock); watcher.MINE.clear(); watcher._OBS.clear()
    calls = []
    def api(path, payload=None):
        if path.startswith("/svc/match"): return {"display_id": DID}
        calls.append(payload["state"]); return {"ok": True}
    monkeypatch.setattr(watcher, "api", api)
    src = tmp_path / "exports" / NAME; src.write_bytes(DATA)
    return type("E", (), dict(tmp=tmp_path, src=src, calls=calls, clock=clock, nitro=tmp_path / "nitro", arch=tmp_path / "archive", locks=tmp_path / "locks"))

def parts(env): return [p.name for p in env.nitro.iterdir() if p.name.endswith(".part")]

# ---------- atomic claim ----------
def test_only_one_claim_per_file(env):
    a = watcher.acquire(NAME); assert a and watcher.acquire(NAME) is None
    a.release(); b = watcher.acquire(NAME); assert b; b.release()
    assert not list(env.locks.iterdir())

def test_process_skips_a_file_claimed_by_someone_else(env):
    held = watcher.acquire(NAME)
    assert watcher.process(str(env.src)) == watcher.BUSY
    assert env.src.exists() and not env.calls and not list(env.nitro.iterdir())          # untouched, nothing reported
    held.release()

def test_two_workers_at_once_copy_exactly_once(env, monkeypatch):
    gate = threading.Event(); started = threading.Event()
    def hook(n): started.set(); gate.wait(5)                                              # first worker stalls mid-copy
    monkeypatch.setattr(watcher, "COPY_HOOK", hook); results = []
    t1 = threading.Thread(target=lambda: results.append(watcher.process(str(env.src)))); t1.start()
    assert started.wait(5)
    assert watcher.process(str(env.src)) == watcher.BUSY                                  # second worker while the first is mid-copy
    gate.set(); t1.join(10)
    assert env.calls.count("ON_NITRO") == 1 and not parts(env) and (env.nitro / NAME).read_bytes() == DATA
    assert len(list(env.arch.iterdir())) == 1 and not env.src.exists()

def test_source_already_archived_by_other_worker_is_not_an_error(env):
    env.src.unlink(); assert watcher.process(str(env.src)) == watcher.DONE and not env.calls

# ---------- stale / dead locks ----------
def _write_lock(env, **info):
    lp = env.locks / (NAME + ".lock"); lp.write_text(json.dumps(info)); return lp

def test_lock_of_another_host_is_respected_until_it_stops_refreshing(env):
    _write_lock(env, host="other-box", pid=1, token="t")
    assert watcher.acquire(NAME) is None                          # first look: just started observing
    env.clock.t += watcher.LOCK_STALE - 1; assert watcher.acquire(NAME) is None
    env.clock.t += 2; c = watcher.acquire(NAME); assert c        # unchanged for LOCK_STALE by our clock: dead, taken over
    c.release()

def test_refreshed_lock_is_never_stale(env):
    lp = _write_lock(env, host="other-box", pid=1, token="t"); assert watcher.acquire(NAME) is None
    for _ in range(5):
        env.clock.t += watcher.LOCK_STALE - 10; os.utime(lp, (time.time() + _ + 1, time.time() + _ + 1))      # owner heartbeat changes mtime
        assert watcher.acquire(NAME) is None

def test_lock_of_dead_pid_on_this_host_is_broken_immediately(env):
    p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()
    _write_lock(env, host=watcher.HOST, pid=p.pid, token="t")
    c = watcher.acquire(NAME); assert c; c.release()

def test_leftover_lock_from_previous_life_with_same_pid_is_broken(env):
    _write_lock(env, host=watcher.HOST, pid=os.getpid(), token="from-before-restart")     # container restart: pid 1 again, token never issued by us
    c = watcher.acquire(NAME); assert c; c.release()

def test_lock_stolen_mid_copy_aborts_cleanly(env, monkeypatch):
    def hook(n):
        lp = env.locks / (NAME + ".lock"); lp.write_text(json.dumps({"host": "x", "pid": 1, "token": "thief"})); env.clock.t += 60   # forces a refresh check
    monkeypatch.setattr(watcher, "COPY_HOOK", hook)
    with pytest.raises(watcher.LockLost): watcher.process(str(env.src))
    assert env.src.exists() and not (env.nitro / NAME).exists() and not parts(env) and "ON_NITRO" not in env.calls
    assert json.loads((env.locks / (NAME + ".lock")).read_text())["token"] == "thief"       # we did not delete the thief's lock

# ---------- stale .part cleanup ----------
def test_part_cleanup_is_safe(env):
    tok = "a" * 32; live = env.nitro / (".%s.%s.part" % (NAME, tok)); live.write_bytes(b"x")
    old = env.nitro / (".other.mov.%s.part" % ("b" * 32)); old.write_bytes(b"y")
    legacy = env.nitro / ".legacy.mov.part"; legacy.write_bytes(b"z")
    keep = [env.nitro / "real.mov", env.nitro / ".hidden_but_not_ours", env.nitro / "notes.part.txt"]
    for k in keep: k.write_bytes(b"keep")
    claim = watcher.acquire(NAME);
    live.rename(env.nitro / (".%s.%s.part" % (NAME, claim.token))); live = env.nitro / (".%s.%s.part" % (NAME, claim.token))   # owned by a live claim
    watcher.clean_stale(); assert old.exists() and legacy.exists()                        # not stale yet: first observation
    env.clock.t += watcher.PART_STALE - 1; watcher.clean_stale(); assert old.exists()
    env.clock.t += 2; watcher.clean_stale()
    assert not old.exists() and not legacy.exists()                                       # unchanged + no live owner: removed
    assert live.exists() and all(k.exists() for k in keep)                                # live owner's part and foreign files untouched
    claim.release()

def test_growing_part_is_not_deleted(env):
    p = env.nitro / (".%s.%s.part" % (NAME, "c" * 32)); p.write_bytes(b"1"); watcher.clean_stale()
    for i in range(4):
        env.clock.t += watcher.PART_STALE - 5; p.write_bytes(b"1" * (i + 2)); watcher.clean_stale(); assert p.exists()   # still changing = still being written

def test_orphan_lock_for_vanished_source_is_cleaned(env):
    p = env.locks / "gone.mov.lock"; p.write_text(json.dumps({"host": "other", "pid": 1, "token": "t"}))
    watcher.clean_stale(); assert p.exists()
    env.clock.t += watcher.LOCK_STALE + 1; watcher.clean_stale(); assert not p.exists()

# ---------- restart during copy (real process, kill -9) ----------
CHILD = textwrap.dedent('''
    import sys, time, pathlib; sys.path.insert(0, %r)
    import watcher
    t = pathlib.Path(%r)
    for k, n in (("EXPORTS","exports"),("NITRO","nitro"),("ARCH","archive"),("QUAR","quar"),("LOCK_DIR","locks")): setattr(watcher, k, str(t / n))
    watcher.NEED_PROBE = False; watcher.CHUNK = 4096
    watcher.api = lambda path, payload=None: {"display_id": %r} if path.startswith("/svc/match") else {"ok": True}
    def hook(n): (t / "copying").touch(); time.sleep(60)          # stall mid-copy so the parent can kill us
    watcher.COPY_HOOK = hook
    watcher.process(str(t / "exports" / %r))
''')

def test_kill_9_during_copy_then_restart_recovers(env):
    child = subprocess.Popen([sys.executable, "-c", CHILD % (str(root / "autoid_lite"), str(env.tmp), DID, NAME)])
    try:
        for _ in range(100):
            if (env.tmp / "copying").exists(): break
            time.sleep(0.1)
        else: pytest.fail("child never started copying")
        assert len(parts(env)) == 1 and (env.locks / (NAME + ".lock")).exists()         # crash scene: partial copy + lock left behind
        child.kill(); child.wait()                                                       # kill -9, no cleanup code runs
    finally: child.kill()
    assert not (env.nitro / NAME).exists() and env.src.exists()                          # Nitro never saw a partial file under the real name
    crashed_part = parts(env)[0]
    assert watcher.process(str(env.src)) is None                                         # restarted watcher: dead pid, lock broken at once
    assert (env.nitro / NAME).read_bytes() == DATA and env.calls.count("ON_NITRO") == 1
    assert len(list(env.arch.iterdir())) == 1 and not env.src.exists() and not (env.locks / (NAME + ".lock")).exists()
    assert parts(env) == [crashed_part]                                                  # the dead worker's partial is still there ...
    watcher.clean_stale(); env.clock.t += watcher.PART_STALE + 1; watcher.clean_stale()
    assert parts(env) == []                                                              # ... and is removed once safely stale

def test_restart_after_copy_before_archive_is_idempotent(env, monkeypatch):
    real_move = watcher.shutil.move
    def boom(*a, **k): raise OSError("crash before archive")
    monkeypatch.setattr(watcher.shutil, "move", boom)
    with pytest.raises(OSError): watcher.process(str(env.src))
    assert (env.nitro / NAME).exists() and env.src.exists() and not parts(env)           # copied + verified, source still in Exports
    monkeypatch.setattr(watcher.shutil, "move", real_move); watcher.MINE.clear()
    watcher.process(str(env.src)); assert not env.src.exists() and len(list(env.arch.iterdir())) == 1
    assert hashlib.sha256((env.nitro / NAME).read_bytes()).hexdigest() == hashlib.sha256(DATA).hexdigest()

def test_source_changed_during_copy_is_rejected_and_cleaned(env, monkeypatch):
    def hook(n):
        if not hasattr(hook, "done"): hook.done = True; env.src.write_bytes(DATA + b"more")      # editor still writing
    monkeypatch.setattr(watcher, "COPY_HOOK", hook)
    with pytest.raises(IOError): watcher.process(str(env.src))
    assert not (env.nitro / NAME).exists() and not parts(env) and "ON_NITRO" not in env.calls
