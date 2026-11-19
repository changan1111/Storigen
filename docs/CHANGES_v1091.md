# v10.9.1 - a story renamed in Blaze takes its clip name with it

**Request:** when the story name changes in Blaze (example: "karthik test"), Storigen noticed the change but the clip name / ID stayed "karthik test", so the editor was still told to name the file with the old name. Fix it. Nothing else changes.

## What was wrong
* The poller saw the new title (`SLUG_TITLE`) and the story's name on the dashboard did update.
* The clip NAME (`name_id`, `DDMMYY_STORY_NAME`) is made from the story title **once, when the clip is created**, and was never touched again. The desk, the watcher (file name -> clip) and the Blaze media match all work on that name, so after a rename a file named with the new title found no clip, and the clip kept waiting under the old name.

## What happens now
* When the Blaze story ID is the same but its title changed, every clip of that story that is still **WAITING_FOR_CLIP** (no file seen, nothing sent) gets the name of the new title. An ending is kept: `..._V2`, `_U01`, `_V01` follow the new base name.
* A clip whose file is already on its way (EXPORTING, VERIFIED, ON_NITRO, ATTACH_SUBMITTED), attached or held keeps its name: the file on Nitro carries it, and matching it by a new name would lose it. The story's name on the card still follows.
* A title that changes only in capitals, spaces or punctuation (same file-safe name) changes the card, not the clip name, and says nothing.
* The **internal ID** (`display_id`, e.g. `20261119_0001T_KARTHIK_TEST`) never changes: the ledger, the files table and the history are keyed on it.
* The desk gets an alert: `Story renamed in Blaze (bulletin): 'old' -> 'new'. The clip name is now ... (was ...)`, and the event log gets a `story_renamed` entry.
* A file still exported with the **old** name is refused with a reason (the watcher shows it): `this story was renamed in Blaze: the clip name is now X, not Y. Name the file X`. It is refused on purpose: accepting it would put a file on Nitro under a name no clip has, and the poller could not find it in Blaze.
* `ID_FORMAT=legacy` (the display ID is the name) is not changed.

## Under the hood
* `autoid_lite/server.py`: `upsert_story_row` detects the title change and calls the new `rename_clips`; `old_name_hint` finds the earlier name. `autoid_lite/api_service.py`: `s_sync`, `s_story` (and so the poller and the MOS gateway) alert after the transaction; `s_match` explains an old name.
* `autoid_lite/db.py`: one new small table `clip_old_names` (additive, created at start; the schema number stays 10; nothing is deleted and an older program still opens the database).

## Not covered (by design)
* If Blaze ever gives a renamed story a **new story ID** (not a rename of the same story), it is a different story to Storigen: the old one is "removed" (clip held, NEEDS DESK) and a new one is made. That would show in the poller log as `STORY_REPLACED`. If you see that for a plain rename, send me that log line.

## Tests
`tests/test_story_rename.py` (9 tests): the new name, the internal ID unchanged, the old name refused with the reason, same file-safe name = no change, a clip already on Nitro keeps its name, `_U01` / `_V01` follow, a story in two bulletins, the alert and event log, legacy untouched, and the whole way through the real poller. With the fix switched off, 6 of them fail.

## Upgrade
Back up `data`, replace the program files (keep `autoid.env` and `data`), restart both services, Ctrl+F5 once; the page header must say v10.9.1. No settings, no new database.
