# v9.2: dashboard and report page (changes on top of v9.1)

Nothing in the watcher, gateway, database schema, live-attach rules or the Blaze write boundary was changed. 141 tests pass (134 from v9.1 + 7 new).

| File | Change |
|---|---|
| `autoid_lite/web/index.html` | The page is restyled as a story tracker: header with a service status pill, count cards (total, on Nitro, needs desk, waiting, attached), filters All / Action / Waiting / Done, story cards (title, state, show, row, clip ID, Blaze story ID), a selected-story panel with the media file and a history timeline, and a "Tool vs desk report" button. Everything the old page did is kept: login, day picker, Create ID, Copy ID, + Version, Open in Blaze, Mark attached, recent activity, user admin. All text from Blaze is shown with `textContent` (never as HTML). |
| `autoid_lite/server.py` | New `GET /api/clips/<id>/history` (login): the steps and media file for one clip, built from what the registry recorded. New `GET /report` and `GET /report/YYYYMMDD` (same login): serves `agreement_YYYYMMDD.html` from the reports folder; only that file name pattern is ever read. `reports_dir` setting (`BLAZE_REPORT_DIR`, default `data/reports`). Version string `lite-1.1`. |
| `tools/blaze_ledger.py` | `render_html()`: the styled, self-contained report page (all dynamic text escaped). The CSV gets a `row` column. |
| `tools/blaze_poll.py` | `report` also writes the HTML page. The poller refreshes today's HTML about once a minute (written through a temp file, so a half-written page is never served; the CSV is not rewritten each minute, so an open Excel file is never touched). A failing report write is logged once and never stops polling. `summary` and the page share `five_days()`. |
| `tests/test_dashboard.py` | New: history steps and problem step, login needed, report route (login, only report files, path tricks refused, missing day), HTML escaping, counts on the page, poller writes the page without touching the CSV, a failing write does not stop polling. |
| `docs/INSTALL.html` | New section 7A: the dashboard and the report page. |

## Checked in a real browser
The dashboard was driven in headless Chromium against a running server: login, cards, filters, the detail timeline, a needs-desk problem step, and a story title containing HTML (shown as text, nothing executed). The report page was opened the same way. **Not tried on your real Blaze, your real Nitro or a real Windows PC.**

## Not changed (known)
- The tool-vs-desk comparison is computed by the poller from its own ledger, so the report page appears only while the poller runs.
- The dashboard shows each story's row position as last reported by Blaze.
