# v10.11.0 - Delete icon on every clip, and the Clip assistant (chat) on every page

Two new features. **Quick Support is not changed** (`api_support.py` and `blaze/support.py` are byte for byte the v10.10.1 files; a test pins them by hash).

## 1. Delete icon next to the preview
* A red **🗑 Delete** button sits next to **▶ Play preview** on every clip: on each clip row of the Story Media Gallery (stories with several clips) and in the single *Preview* box (stories with one clip). Also when Preview is switched off.
* It is enabled only for a clip that is **attached in the story** (ATTACHED, with its Blaze clip ID, not already replaced). Otherwise it is greyed and the tooltip says why. It is greyed too for a role without the *attach* right and when `SUPPORT_MENU=0`.
* Click: the page asks Blaze (through the read-only Support *list* request) which clips the story holds, then shows **Yes / No**:
  *"Deleting here deletes the clip everywhere this story is in the rundown: N bulletins (names). It cannot be undone from here."* plus *"The file itself stays in Nitro."* and, for a bulletin that has aired, *"A change made now may not reach the air."*
* **Yes** sends the Support *remove* request; the poller deletes it under the Quick Support rules (kill switch, `BLAZE_ATTACH`, one attempt, read-back). Everyone signed in gets the same notification as for a Support delete. The clip's ID becomes *Needs desk*, so the automatic attach never puts it back.
* **No** (or a click outside the box) does nothing.
* Needs the Blaze poller running, like every Support request.

## 2. Clip assistant (chat)
* A round **💬** button at the bottom right of **every page** (Rundown, Stories, Media, Ready, Support, Activity, Users, Reports). It stays visible when the Ready feed panel is open. Esc or ✕ closes it; ↺ starts again.
* Button-driven, no typing needed: **bulletin** (today by default, *Another day…* for a date) → **story** (search box) → **Append** or **Update**.
* It shows what the story holds now (every clip and its state), that the story is in several bulletins (one file serves all), and warnings (bulletin already aired; `VERSION_SUFFIX` off).
* **Append** = one more clip next to the ones already there. It gives the exact next name by the Clip Naming Rule Book: `DDMMYY_SLUG_V01`, then `_V02` ... (next number only, two digits). Nothing is removed.
* **Update** = replace a clip. It lists the clips that are there (the main clip and each added clip) and the editor picks one: main clip -> `..._U01`, `..._U02`; added clip V01 -> `..._V01_U01`, `..._V01_U02`. U and V are counted separately. It reminds: do not delete the old clip in Blaze yourself; do not use `_V` for a correction.
* **Copy name** button, then **I exported it - check**: the assistant reads the story again and says whether the system has seen that file name and its state.
* The assistant **only reads**. It never writes to Blaze, never creates a clip ID, never makes a Support request. It works even when `SUPPORT_MENU=0`.

### Calls (read-only, same sign-in and *view* right as the dashboard)
`GET /api/bot/bulletins?day=YYYYMMDD` | `GET /api/bot/stories?rundown=<show id>` | `GET /api/bot/story?rundown=<show id>&story=<Blaze story id>`
The last one returns the base name, every clip (name, state, replaced), the main clip slot and each added-clip slot with their next `_U` name, `next_v`, the bulletins holding the story and whether `VERSION_SUFFIX` is on. New file `autoid_lite/api_bot.py` (`plan_names` is a pure function). No database change.

## Notes
* The names are for `VERSION_SUFFIX=on` (the rule book's `_V` / `_U`). With it off the assistant still gives the names but warns that the system will not pick them up by itself.
* The registry holds the next number once the watcher has seen the previous file, so after exporting `_V01` press *check* before asking for the next name.
* Sample dashboard (`tools/make_standalone.py`): the assistant and the Delete icon work on the made-up stories; the delete changes only the sample.

## Tests
`tests/test_bot_and_delete_icon.py` (11 tests): Support files unchanged, next numbers (V, U, V01_U01 chains, 99 limit, same clip in two bulletins), the three assistant calls against the fake Blaze, names move on after a `_V01` is registered, works with Support off, writes nothing, the clip the icon deletes is the one the dashboard shows and the delete goes through, page wiring (icon in both places, Yes / No before delete, assistant built once and read-only). Also driven end to end in headless Chromium on the sample page (chat flow, delete Yes / No, disabled icons). Whole suite: 550 passed; the two failures (`test_preview::test_the_switch_and_the_missing_ffmpeg_are_reported`, `test_blaze_poll::test_report_classes_without_a_server`) also fail on the untouched v10.10.1 files in a machine without ffmpeg.

## Upgrade
Replace the program files (keep `autoid.env` and `data`), restart, Ctrl+F5 once; the page header must say v10.11.0. No setting to change.
