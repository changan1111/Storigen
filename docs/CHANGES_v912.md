# v9.12 (Storigen)

Everything of v9.11 plus:

* **No folders needed:** `WATCHER_ENABLED=0` in `autoid.env` does not start the watcher at all. No Playout / Nitro mount is needed, the red "NAS or Nitro folder not reachable" warning and its alerts are gone (an old watcher heartbeat in the database is ignored too), `doctor` skips the folder check, and the dashboard shows only the NITRO and ATTACHED steps. Default stays `1`, so nothing changes for an install that has the folders mounted. Use it with `BLAZE_ATTACH_WHEN=media` (default): the file found in Blaze's media list is what counts.
* `/api/config` reports `watcher_enabled`. Version `9.12`.
* Tests: `tests/test_watcher_disabled.py`.
