# v10.18.0 - A clip added with the + (Add media) button now shows on the dashboard and can be played

## What was wrong (three separate things)
1. **It waited for the poller.** A clip added with + was shown only after the poller's next full read of the story reached the server. If that report was late, skipped or lost, the dashboard showed nothing.
2. **The story card said nothing.** The "N clips in this story" count was only worked out when `VERSION_SUFFIX=on` (it is `off` by default), so with the default setting the added clip appeared nowhere on the card.
3. **No preview.** The card said "No preview or checks": Storigen has no Nitro record for a clip it did not make, and Play was built on that record.

## What changed
* **Shown at once.** When a Support add finishes (DONE) with the new clip's ID, the server puts that clip into the story's clip list straight away, from the poller's own result. The poller's normal full report still replaces the list afterwards with what Blaze really holds (and adds the duration). Nothing is sent to Blaze by this.
* **Story card.** A story that holds clips Storigen did not make now shows **"+ N clip(s) added in Blaze (not made by Storigen)"** whatever `VERSION_SUFFIX` is. With `VERSION_SUFFIX=on` it still shows the usual "N clips in this story".
* **Play preview on those cards.** The card has **Play preview** (and Stop). Because there is no record, the server looks for the file **by the clip's name** in the Nitro ONAIR folder **every time Play is pressed**, then streams it exactly like the other previews (low resolution, ffmpeg, one at a time, low priority).
  * It uses the settings the watcher already uses: `NITRO_DIR`, `NITRO_DATE_PATH`, `NITRO_SCAN_DAYS_BACK` / `_AHEAD` (today first, then the days around it), `NITRO_EXTS`, `NITRO_SCAN_DEPTH`. Spaces, dashes, underscores and capitals do not matter in the name. If several files match, the newest wins.
  * **Nothing is stored or cached**: no list of files, no thumbnail, no temp file, nothing in the project folder. Nothing runs until someone presses Play, so the poller, the watcher and the page are not slowed.
  * If the file is not found the message says what was looked for and in which day folders (it may not be on Nitro yet, or it has another name there).
  * The server only ever streams a file inside `NITRO_DIR`; a clip name cannot point anywhere else (tested with `../../secret` and `/etc/passwd`).
* The new address is `GET /api/blaze-clip/preview?story=<Blaze story id>&clip=<Blaze clip id>` (login needed). It finds the clip by ID in the list the poller reported; the browser never sends a file name or path.

## Not changed on purpose
`api_support.py` and `blaze/support.py` are byte-for-byte as in 10.10.1 (a test pins them), and the poller is untouched. The new step lives in a wrapper around the Support result (`api_blazeclips.py`). **Only the web service needs a restart**; the poller does not.

## Needs from your side
The web service must see the Nitro folder and have ffmpeg (the same two things the normal Play already needs). Hand-added clips still get no quality checks, frames or AI checks.

## Tested, and what is not
`tests/test_v10180.py` (10 tests): the name lookup (nested folders, name rules, closest day first, far days ignored, no day folders, missing folder), a finished add showing at once with `VERSION_SUFFIX` off, a repeat or failed or ID-less result adding nothing, the poller's full report replacing it, the real stream through ffmpeg with nothing left behind, every failure message, a name never leading outside `NITRO_DIR`, and the page. The rest of the suite is unchanged apart from the version numbers and one pinned line of `startPreview`: 618 passed. **Not tested: the real Blaze, your real Nitro share, and a real browser** (no Chromium on the build machine, so the browser tests were skipped): please press Play on a clip added with + before the desk relies on it. If the Blaze clip title differs from the MXF file name on Nitro, tell me one example of each and I will add the rule.

# v10.18.1 - Groq "secure connection could not be made" on a Mac
`curl` and `nc` reach api.groq.com from the same Mac, so the network, firewall and clock are fine. Storigen runs on Python, and a Python installed from python.org has no certificates of its own until `Install Certificates.command` is run, so its check of Groq's certificate failed ("certificate verify failed") and the message blamed a proxy or the clock.
* The Groq call now uses `SSL_CERT_FILE` if set, else the `certifi` package if installed, else the system bundle (`/etc/ssl/cert.pem` on a Mac). No setting needed.
* The message now names this case and what to do. Restart the web service. Not tested against the real Groq.

# v11.0.0 - Groq 400 / 404: Groq's own reason is shown
Any 400 or 404 used to say only "could not use the model". It may be the model name, or the request itself. The message now adds Groq's own text (never the key).
To list the models your key can use (Terminal):
`curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer YOUR_KEY" | grep '"id"'`
