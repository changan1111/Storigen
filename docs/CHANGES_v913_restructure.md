# v9.13, restructured build (no behaviour change)

Everything of v9.13. Same commands, same settings, same dashboard, same speed. Verified by the full test suite (307 tests: the original 300 plus 7 new) and by `tools/bench_polling.py` (same figures within noise: first round 6.9 s, steady 2.0 s, busy round 4.6 s, same request counts, same changes detected).

* **Poller split into a package** `autoid_lite/blaze/`. The 1,166-line `tools/blaze_poll.py` is now 165 lines of command line; the engine lives in small modules (`safety.py` holds the whole write wall in 11 lines). `tools/blaze_poll.py` still exports everything it did, and `tools/blaze_ledger.py` / `blaze_snapshot.py` still import as before.
* **Server split**: the 630-line `App` class is now a core plus three mixins (`api_service.py`, `api_auth.py`, `api_dashboard.py`); constants and helpers are in `common.py`; `server.py` re-exports them.
* **Versioned database schema** (`PRAGMA user_version`, append-only `COLUMNS` list in `db.py`). Existing databases upgrade as before; a database from a newer program is refused with a clear message.
* **Fixed: `autoid.py selftest` failed** ("web page is served"): it looked for the old name "Auto-ID Linker" in a page that has been Storigen since 9.8.1. Now checks for Storigen, and a test runs the self-test.
* **Clip states in one place** (`autoid_lite/states.py`).
* **Tests renamed by feature** instead of by version (`test_v975_stages.py` is now `test_four_step_strip_and_dry_wall.py`, and so on). One test that read the old poller file as text now reads the files the code moved to; what it checks is unchanged.
* New docs: `docs/ARCHITECTURE.md`, `docs/CHANGELOG.md` (index of all release notes).
* Version string stays `9.13`, so the Install and Operations Guide stays in sync.
