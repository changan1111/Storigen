# v9.8.1 (Storigen final)

Everything of v9.8.0, rebranded from NewsFusion to **Storigen**.

* **Logo:** the supplied Storigen logo ("Every Story is Connected.") is used as is on the sign-in page and in the dashboard header. The image is only trimmed of its empty margins and shrunk to 1200 px wide (WebP, about 28 KB), then embedded in `index.html` as a data URI, so there is no extra file to serve. It sits on a white plate, so it reads in light and dark mode.
* **Name:** page title, browser-tab title, footer (`Storigen 9.8.1`), the start-up line in the console and the README now read "Storigen".
* **Version:** `/api/config` and `/health` report `9.8.1`.
* **Unchanged on purpose:** internal names (`autoid.py`, `autoid.env`, the `autoid_lite` package, localStorage keys, database file) so existing installs, saved settings and data keep working. Upgrade by replacing the files and restarting; no database change.
* **Tests:** `tests/test_branding_signin_and_header.py` now checks for Storigen, and `tests/test_storigen_logo.py` checks that the embedded logo is the Storigen image and that no NewsFusion text is left in the page.

## Fix: expired Blaze session was not recovered
Blaze answers an expired or replaced session with `HTTP 400 {"errors":["invalid.sessionId"]}`. The poller only knew 401, 403 and 404, so it printed one PROBLEM line and then repeated "Blaze listed no shows ... nothing to follow yet" without logging in again. 400 `invalid.sessionId` now counts as an expired session: the poller picks up a new cookie from `autoid.env` or logs in again by itself (BLAZE_USERNAME + BLAZE_PASSWORD_HASH). Test: `test_981_04`.

Run only ONE poller per Blaze user. `autoid.py` with `BLAZE_POLL=1` already starts it; a second `blaze_poll.py run` by hand logs in as the same user and can replace the other one's session.

## Fix: live attach needed the NAS watcher even with BLAZE_ATTACH_WHEN=media
With `BLAZE_ATTACH_WHEN=media` (the default) the file found in Blaze's media list is enough, as the setting says. The poller's last live check and the server's attach confirmation still demanded the state ON_NITRO, which only the NAS watcher sets, so with the NAS not mounted a clip with NITRO green was never attached. Now `media` mode attaches clips that wait for a clip (WAITING_FOR_CLIP, EXPORTING, VERIFIED, ON_NITRO) once Blaze has their file; `watcher` mode still waits for ON_NITRO. All the other rules stay: one settled, converted file, a verified story format, quicktest scope, kill switch, hourly limit, read-back after the attach.
