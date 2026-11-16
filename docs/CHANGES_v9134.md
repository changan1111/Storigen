# v9.13.4

**Problem:** after copying a new version over the installed folder and restarting, the dashboard board was empty ("Cannot reach the service") while the log still showed entries. `GET /api/clips` answered `500 {"detail": "internal error"}`; the server log held `ERROR GET /api/clips: OperationalError('no such column: ...')`.

**Cause:** the database upgrade skipped every column up to the version stored in the database (`PRAGMA user_version`). A database stamped with the current version but missing a column (for example `qa_state`, `online_script`) was never repaired, and the dashboard query failed.

**Fix:** `db.py` now checks every declared column on every start and adds any that is missing; data is kept. The stored version is only updated when it differs.

* **Files changed:** `autoid_lite/db.py`, `autoid_lite/common.py` (version 9.13.4), docs, tests.
* **Tests:** `test_schema_migrations.py` gains a test for a database stamped with the current version but missing columns; the two version checks expect 9.13.4.
* **Upgrade:** copy over the folder (keep `autoid.env` and `data`), restart. If the board is still empty, the log line `ERROR GET /api/clips: ...` names the cause.
