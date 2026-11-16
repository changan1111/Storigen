# v9.7.3 - the poller logs in to Blaze by itself

## What changed
Until now the Blaze session (`BLAZE_SESSION_ID` + `BLAZE_USERNAME`) had to be copied by hand from a browser tab and stopped working when it expired.
Now the poller does what the Blaze page does: `POST /DataService/sessions` with the form `username`, `password`, `_` (milliseconds).
Blaze answers `201`, empty body, and the new session ID in `Set-Cookie: sessionId=...;Version=1` and in `Location: .../sessions/<id>`.

## Settings (autoid.env)
| Setting | Meaning |
|---|---|
| `BLAZE_USERNAME` | the Blaze user (as before) |
| `BLAZE_PASSWORD_HASH` | NOT the typed password: the `password=` value the Blaze page sends in its login request (DevTools > Network). A percent-encoded copy (`%2B`, `%2F`, `%3D`) is accepted as it is. Treat it like a password. |
| `BLAZE_SESSION_ID` | may stay empty: the poller logs in at start and writes the new session into this line |
| `BLAZE_AUTOLOGIN` | `1` (default when username and hash are set) / `0` = cookies only, as before |
| `BLAZE_LOGIN_MIN_SECS` | pause between login tries, default 60 (minimum 5) |
| `BLAZE_LOGIN_MAX_FAILS` | failed logins in a row before auto-login stops, default 3 |

## How it behaves
1. **Start:** no session ID but a login configured -> logs in first. One-off read-only commands (`show`, `media`, `probe`, `map`, `shows`) with an expired cookie log in and run once more.
2. **Running:** when any Blaze call says the session is gone (404 authenticationFailed, 401/403, or a login page), the order is: a different cookie in autoid.env wins (as before) -> else log in again -> else the old alert.
3. **The call that failed is never repeated by the login.** An attach that met an expired session stays "unclear whether it arrived" exactly as in v9.7.2; the next round uses the new session and the read-back decides. `once`, `undo`, `live-retry` and the other commands that can write never log in and run again behind your back.
4. **Protection of the account:** at least `BLAZE_LOGIN_MIN_SECS` between tries; after `BLAZE_LOGIN_MAX_FAILS` failures in a row auto-login pauses and an alert is sent (a wrong hash sent every 15 seconds could lock the user). A fresh cookie in autoid.env or a restart re-enables it.
5. **Written back:** only the `BLAZE_SESSION_ID` line of autoid.env is changed (temp file + swap); every other line and comment stays as it is. If the file cannot be written, the session is kept in memory and the log says so.
6. **Nothing secret is printed:** not the hash, and only the last 4 characters of a session ID.
7. **The write boundary** gets exactly one new entry: `POST /DataService/sessions`. Every other write (attach, undo, script-duration update, keep-alive PUT) is as in v9.7.2; anything else still raises `ForbiddenCall`.

## Files
`tools/blaze_poll.py`, `autoid_lite/config.py` (`set_env`), `autoid_lite/server.py` (version), `autoid.env.example`, `tests/test_blaze_poll.py` (the fake Blaze answers the login), `tests/test_blaze_auto_login.py` (new, 16 tests), `tests/test_clip_names_and_versions.py` (version check; also pins CHECK_CHAR so the suite passes in any order).

## Not verified here
The login was tested against a fake Blaze built from your capture, not against the real server. It assumes `password` is a fixed value (a hash of the password), not one that changes on every login. If the real server refuses it, the log shows `LOGIN FAILED (1 of 3): Blaze refused the login (HTTP ...)` and nothing else is affected.
