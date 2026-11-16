# Storigen architecture (developer notes)

Standard library only. Runs the same on Mac and Windows. Operators use `docs/Storigen_Install_and_Operations_Guide.pdf`; this file is for whoever changes the code.

## Processes (started by `autoid.py run`, restarted if they crash)

| Process | Entry point | Job |
|---|---|---|
| server | `python -m autoid_lite.server` | Web page, JSON API, SQLite database `data/autoid.db`. The only writer of that database. |
| watcher (optional) | `autoid_lite/watcher.py` | Reads the Playout INBOX and Nitro ON AIR folders (observe mode by default). `WATCHER_ENABLED=0` = not started. |
| Blaze poller (`BLAZE_POLL=1`) | `tools/blaze_poll.py run` | Reads shows from Blaze, finds media, attaches (live or one confirmed Quick test). |
| gateway (`MOS_ENABLED=1`) | `autoid_lite/gateway.py` | MOS device feeding story IDs to the server. |

The watcher, the poller and the gateway talk to the server only over HTTP (`/svc/*`, API key). The poller keeps its own ledger and snapshot SQLite files and is the only process that holds the Blaze session.

## Code layout

```
autoid.py                      launcher: init, run, status, doctor, selftest, backup
autoid_lite/
  server.py                    App core (+ HTTP handler, serve, main). Re-exports what moved out.
  common.py                    version, errors, Req, settings_from_env
  states.py                    clip states, ONE copy for server and poller
  api_service.py               ServiceMixin   /svc/*  feeds, attach confirm, quick-attach result, health
  api_auth.py                  AuthMixin      sign-in, roles, users
  api_dashboard.py             DashboardMixin /api/*  clips, rundowns, versions, history, CSV, report page
  db.py                        SQLite: tx(), backup, VERSIONED schema (see below)
  security.py  ids.py  config.py  alerts.py
  watcher.py  gateway.py
  web/index.html               single-file dashboard
  blaze/                       the poller engine
    safety.py                  THE WALL: WRITE_ALLOWED + check_call + ForbiddenCall. Audit this file first.
    errors.py states.py util.py scope.py
    keys.py                    pure matching helpers (file name -> clip key, media index, judge, attach body)
    settings.py                Cfg
    client.py                  Blaze (DataService client), AutoId (server client)
    poller.py                  Poller core: read shows, sync, identity, events
    media.py attach.py reports.py loop.py     Poller method groups (mixins)
    scripts.py                                reads each story's two script fields (text1 / text2) for the dashboard (v9.13.2)
    lock.py envcheck.py                       one poller at a time; has autoid.env changed since the poller started (v9.13.1)
    ledger.py snapshot.py      the poller's own SQLite ledger and per-round snapshot
tools/blaze_poll.py            command line (run, shows, map, live, undo, ...) and re-exports of the whole engine
tools/blaze_ledger.py, blaze_snapshot.py   aliases of blaze/ledger.py, blaze/snapshot.py (same module object)
```

`tools/blaze_poll.py` keeps every documented command and still exposes `bp.Poller`, `bp.Cfg`, `bp.media_key`, ... so existing scripts and tests work unchanged.

## Rules that keep it safe (do not weaken)

1. **One wall.** Every call to Blaze goes through `check_call`. The only writes that can pass are in `WRITE_ALLOWED` (login, keep-alive, attach, undo, script duration). In `dry` the Blaze client refuses attach and duration updates except for one story inside a confirmed Quick test (`BlazeClient.quick()`).
2. **Dry by default; one attempt per clip; read back after every attach; kill switch `data/STOP_LIVE`.**
3. **Events are append-only** (database triggers).
4. The poller never edits the database directly: it asks the server (`/svc/*`).

## Database schema versions

`autoid_lite/db.py` has `COLUMNS`, an append-only list `(version, table, column, type, why)`. The stored version is `PRAGMA user_version`. To add a column: append one line with the next version number. Never edit or reorder old lines. A database from a newer program is refused with a clear message instead of being half-read. Tests: `tests/test_schema_migrations.py`.

## How to add a setting / a clip column / an endpoint

* Setting: read it in `settings_from_env` (server) or `blaze/settings.py` (poller), add it to `autoid.env.example`, `/api/config` if the page needs it, the guide, and a test.
* Column: see above.
* Endpoint: add the method to the matching mixin and one line to the route table in `App.__init__`.

## Tests

`python3 -m pytest -q tests` (about 50 s, 307 tests). Fake Blaze: `tests/test_blaze_poll.py` (`Fake`). Speed: `python3 tools/bench_polling.py --root .` (simulated Blaze, latencies replayed from a real capture). `tests/test_selftest_passes.py` runs the same `autoid.py selftest` the install guide tells operators to run.

## Known follow-ups (not done on purpose: they change behaviour or data)

* Quick test state lives in four `qa_*` columns of `clip_ids`; a small `commands` table would stop `clip_ids` growing with every new button.
* The three ways to narrow live attach (`QUICKTEST_*`, `BLAZE_LIVE_SHOW_IDS`, `BLAZE_ATTACH_WHEN`) overlap; one allow-list would be easier to explain.
* `web/index.html` is one 119 KB file with the logo embedded; split into static files once the tests that read it as text are made structure-aware.
* Source-text pin tests (e.g. in `test_four_step_strip_and_dry_wall.py`) match exact lines, so running a code formatter over the safety code needs those tests rewritten against the syntax tree first.
* Internal names (`autoid`, `autoid_lite`, `autoid.env`) predate the Storigen name and are kept so existing installs upgrade in place.

## Dashboard refresh rule (v10.1.1)

The page polls every 5 s. A render function must not touch the DOM when the data behind it is unchanged: compare with `changed(key, data)` / `setText` / `setHref`, reuse row nodes (`rowNodes`), and update ticking text in place. `tools/dev/check_refresh_dom.js` (headless, needs `npm install jsdom` in `tools/dev`) fails if a refresh with unchanged data changes the page at all.

## Ready feed (v10.2.0)

Source of truth is `clip_ids` (`media_found_at`, `media_id`, `media_name`), filled by `POST /svc/media` (the poller, once per media object). `ServiceMixin.s_media` logs `media_found` and calls `App.ready_notify` (background thread, `alerts.send_ready`, `READY_WEBHOOK_URL`) only when the media object is new for a clip. `DashboardMixin.a_feed` serves `GET /api/feed`. The page keeps a `feed.seen` set per day: the first look is not news; later arrivals show a toast. Same rule as everywhere on the page: nothing is rebuilt when its data did not change (`changed("feed", ...)`).

### Ready feed table (v10.3.0)

`renderFeed` builds one `<table>` (header + `tr.fi` rows from `feedRow`), only when `changed("feed", ...)` says the data changed. Rows are newest first (`ORDER BY media_found_at DESC, id DESC` on the server, sorted again in `loadFeed`). The row's Quick test button does not have its own rules: `feedAdapt(it)` shapes the feed item like a story card's clip and calls the same `qaWhyAll` / `quickAttach`, and the server re-checks everything in `a_quickattach`. `feedJump` resets filter, search and bulletin before opening a story, because the main list only holds the current bulletin / filter / search.
