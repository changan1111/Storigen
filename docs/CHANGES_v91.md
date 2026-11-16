# v9.1: long-running fixes (changes on top of v9)

Nothing in the watcher, gateway, supervisor, database schema or live-attach rules was changed. 134 tests pass (109 from v9 + 25 new).

## What changed

| File | Change |
|---|---|
| `autoid_lite/server.py` | `rundown_synced` is logged only when a story was created, restored or removed (was one event per poll: about 5,760 rows a day per show). New `POST /svc/alert` (service key) so the poller can raise an alert. |
| `tools/blaze_poll.py` | **Reconcile reads a story only when its `clipCount` (from the slugs list) changed**, or every `BLAZE_FULL_RECON_SECS` (600 s). Measured: 1,500 reads became 150 per 10 minutes for 150 stories. Without a clip count in Blaze's answer it reads every time, as before. |
| | **Session cookie reload:** when Blaze rejects the cookie, the poller re-reads `BLAZE_SESSION_ID` and `BLAZE_USERNAME` from `autoid.env` and carries on with a new one. No restart. An empty value never replaces a working cookie. |
| | **Alerts:** first expired session and a halted live attach now call the server's alert channels (webhook / email), once. |
| | **Write boundary in code:** `check_call` allows only the keep-alive (PUT sessions), an attach (POST story clips) and the undo (DELETE a clip). Any other write raises `ForbiddenCall` before a request is built. `attach()` also refuses unless `BLAZE_ATTACH=live`. |
| | Memory stays flat: per-story and per-clip caches forget what left the followed shows. |
| `autoid.env.example` | `BLAZE_FULL_RECON_SECS=600` |
| `tests/test_blaze_poll.py` | Flaky test fixed (`test_core.py` sets `CHECK_CHAR` for the whole test run; the test now uses the poller's own search key). |
| `tests/test_longrun.py`, `tests/test_poll_longrun.py` | New: quiet polls write no event, audit table stays append-only, alert route, fewer reads, periodic re-read, failed read not remembered, forgetting, cookie reload, alerts, write boundary. |

## Windows and Mac
| File | Change |
|---|---|
| `autoid_lite/watcher.py` | `pid_alive` no longer calls `os.kill(pid, 0)` on Windows (it terminates the process there); uses `OpenProcess` / `GetExitCodeProcess`. Only copy mode used it; the default observe mode did not. |
| `tools/blaze_poll.py` | Console output is UTF-8 with replacement, so non-Latin story titles cannot crash a command in a Windows console (child processes already got UTF-8 from the supervisor). |
| `deploy/windows/install_windows.ps1` | Restricts `autoid.env` to the service user and Administrators; turns off standby and hibernate. **Not tried on a real Windows PC.** |
| `tests/test_windows_safety.py` | 5 tests with a faked Windows API. |
| `docs/WINDOWS_CHECKLIST.md` | What to check on the real Windows machine, and the known differences from the Mac. |

## The audit table is still append-only
The `events` table cannot be deleted from or updated (database triggers). v9.1 does not change that. It only stops writing the noise.

## One-off cleanup of noise already written by v9 (optional)
Only worth doing if the database is already large. Stop Auto-ID first and keep a copy of `data/autoid.db`.

```
sqlite3 data/autoid.db
DROP TRIGGER events_no_delete;
DELETE FROM events WHERE action='rundown_synced' AND details LIKE '%"created": 0, "restored": 0, "removed": 0, "held": []%';
VACUUM;
.quit
```
Start Auto-ID again: the trigger is created again at start. Tested on a scratch database: 500 quiet rows removed, real events kept, trigger restored.

## Maintenance rhythm
- Weekly: disk space, size of `data/autoid.db`, remove old show IDs from `BLAZE_SHOW_IDS` (every followed show adds reads).
- Monthly: `data/logs` (capped at 5 MB x 6 files per process), `data/reports`, `data/reports/attach_watch.log` (small, not rotated).
- When Blaze logs you out: put the new cookie into `autoid.env`; no restart.

## Not changed (known)
- A slow Blaze can make one poll longer than the 90 s heartbeat limit and show a false red on the page.
- The watcher writes its small state file with fsync every poll.
- Dynamic show discovery is not in this version: it needs the Blaze call that lists shows for a day.
