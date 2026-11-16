"""One poller at a time. Two pollers that log in as the same Blaze user can replace each other's session (and a stale copy keeps
running its old settings), so `blaze_poll.py run` takes this lock first; a second copy says who holds it and stops."""
from __future__ import annotations
import os
import time
from pathlib import Path


class AlreadyRunning(Exception):
    """Another poller holds the lock; the text is what that poller wrote into the lock file (its pid and start time)."""


_held = []                                   # the open file keeps the lock for the life of the process; the OS frees it when the process ends, even after a crash


def acquire(path):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); fh = open(p, "a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt; fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl; fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try: fh.seek(0); who = fh.read().strip()
        except OSError: who = ""
        fh.close(); raise AlreadyRunning(who or "another poller")
    fh.seek(0); fh.truncate(); fh.write("pid %d, started %s\n" % (os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S"))); fh.flush(); _held.append(fh); return fh
