# v9.7.5

Merge of v9.7.4 full + review fixes, plus NewsFusion branding.

- Sign-in screen really hides after sign-in (`#login.hide` rule).
- `autoid.env` rewrites keep file mode private (600).
- UI: the "Auto-ID" name/mark is replaced by the NewsFusion logo on the sign-in page and in the dashboard header (logo embedded in `index.html` as a data URI on a white plate, so it reads in light and dark mode; no extra file to serve).
- Page title and footer read "NewsFusion". Internal names (autoid.py, autoid.env, localStorage keys) are unchanged so existing installs and saved settings keep working.

## Four-step strip on every story (dashboard)

EXPORT -> ON AIR -> NITRO -> ATTACHED, each green only when it was really recorded:

1. **IN EXPORT (FOLDER)**: the watcher saw the file in a Playout inbox folder; the folder name (NEWS, PROMOS ...) is shown.
2. **ON AIR**: the file left the inbox and the finished MXF is in the on-air (Nitro) folder.
3. **NITRO**: the poller searched Blaze's media list and found the clip's media object (mosObjectId). New `POST /svc/media` records it; it changes no state and sends nothing to Blaze. Needs `BLAZE_POLL=1` and `BLAZE_ATTACH=dry` or `live` (with `off` the poller does not search media).
4. **ATTACHED**: the clip is really attached in Blaze (live attach, read-back of what the desk attached, or Mark attached).

In `BLAZE_ATTACH=dry` the tool never attaches (the attach call raises ForbiddenCall unless live): the first three steps can turn green, ATTACHED stays grey until the desk attaches the clip in Blaze.

## Live attach and QUICKTEST (simple)

- `BLAZE_ATTACH=dry` (default): nothing is ever attached, only logged.
- `BLAZE_ATTACH=live`: real attaches for **every followed show**. This one line is the only switch; the old `BLAZE_LIVE_CONFIRM` lock and the "must list a show" rule are gone, and there is **no hourly limit** by default (`BLAZE_LIVE_MAX_PER_HOUR=0`; set a number only if you want one).
- To try it first, while `BLAZE_ATTACH=live`, narrow it with:
  - `QUICKTEST_STORY_ID=<Blaze story id>`: only that story is attached (several: comma separated);
  - `QUICKTEST_SHOW_ID=<show id>`: only that show is attached (with `BLAZE_SHOW_IDS=auto` use `QUICKTEST_SLOT_ID=<masterId>`, because the show ID changes daily).
  Empty the QUICKTEST_ lines and restart to go fully live. If both are set, a story must match both.
- `python3 tools/blaze_poll.py quicktest <story id>` shows what will happen for that story and sends nothing.
- Still in place: only verified story formats, one settled file, no linked stories, read-back after the attach, kill switch file `data/STOP_LIVE`, and automatic stop after 3 failures in a row.
