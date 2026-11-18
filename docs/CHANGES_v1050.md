# v10.5.0 - more than one clip in a story: `_U01` updates, `_V01` adds (VERSION_SUFFIX=on)

**Request:** a story that already has its clip attached must be able to get more clips later, without anyone clicking **+ Version**.
A file ending `_U01`, `_U02` ... is an UPDATE: it takes the place of the old clip. A file ending `_V01`, `_V02` ... is ADDED next to the clips already there.
The desk must be able to see, while watching, that a story has several clips and that one was updated.

## Off by default
`VERSION_SUFFIX=off` (the default) changes nothing: a name ending `_V2` is read as before, +Version works as before, no extra Blaze call is made. Switch it on in `autoid.env`, restart.
Needs `ID_FORMAT=name` (the default).

## What happens with `VERSION_SUFFIX=on`
1. **The file is seen** (Playout inbox / export folder, as every clip). `111126_FIRE_U01.mxf` -> the watcher asks the registry for that name. When the plain clip `111126_FIRE` exists and `..._U01` does not,
   the registry creates the clip ID under the same story (under every story that holds the plain clip, as a "+ Version for this and later shows" would). A typo with no plain clip stays "not in the registry".
   The same file seen again creates nothing (the database's own uniqueness: same day, number and version). `u1`, `U01` and `U1` are one name.
2. **The clip ID goes through the usual states** (WAITING, ON_NITRO ...). Because it is a clip ID of its own that is not attached yet, the story is looked at again even though its first clip is ATTACHED.
3. **`_Vn` (ADD):** attached next to the clips in the story. Nothing is removed. A `_Vn` never takes the place of anything and is never superseded.
4. **`_Un` (UPDATE):** the existing, verified replace: attach the new clip and read the story back; only when that is exactly right, remove the story's MAIN clip (the plain clip, or the previous `_Un`) and read back again.
   An update never removes a `_Vn` clip. Whatever goes wrong after the attach leaves BOTH clips in the story and alerts the desk (as before). If the story holds more than one possible main clip, nothing is chosen: CHECK flag, the desk decides.
5. **An update that arrives before the plain clip was attached** supersedes it: only the update is attached ("Superseded"), nothing is removed.
6. `BLAZE_ATTACH=dry` still sends nothing; the log line says what it WOULD attach and remove (`REPLACES version 1: Blaze clip ...`). `BLAZE_VERSION_MODE` now only matters for the old numbered versions.
7. **Quick test** works on every clip ID of the story (each has its own button). On a `_Vn` it only adds. On a `_Un` it does the whole replace, even while dry (the one confirmed story, as before).

## How the desk sees it
- Each clip ID is a card of its own, with its own state, Quick test and Play. The card shows **ADDED V01 / UPDATE U02 · 3 clips in this story · latest update U02**.
- In Blaze the clip title is the file name, so the story's attachment list shows `111126_FIRE.mxf`, `..._V01.mxf`, `..._U02.mxf`.
- The **+ Version** button is hidden and refused (409) while the switch is on: versions come from the file name.

## Under the hood (no database change)
No new column or table. `clip_ids.version` holds `1000+n` for `_Un` and `2000+n` for `_Vn` (an ordinary clip is 1; the old +Version numbers 2..999 are not used with the switch on).
`display_id` gets `_U02` / `_V01`; `name_id` is the file name. The matching key stays `(clip name, number)`, so the media list, the ledger, the shared-story marking and the read-back all work unchanged.

## Wall changes (deliberate)
- `delete_clip` now has the same wall as the attach: refused unless `BLAZE_ATTACH=live` or inside a confirmed Quick test.
- `tests/test_four_step_strip_and_dry_wall.py` counted exactly one place that passes `quick=qa`; it now allows the second (the replace of a `_Un` clip) and also checks the delete wall.

## Limits of this first step
- A new file is registered when the watcher sees its name (Playout inbox / export folder). A file that reaches Blaze or Nitro without ever passing there is not registered yet (a later step could read it from Blaze's media list).
- `ID_FORMAT=legacy` is not supported with the switch on.
- How Nitro / Blaze plays several clips of one story on air is the playout system's own behaviour: the tool decides which clips are attached and in which row.
- `autoid_lite/preview.py` is an empty file in the uploaded zip, so 4 preview tests fail with or without this change.

## Tests
`tests/test_version_suffix.py` (14 tests): name reading on and off; the clip ID created once under the same story; nothing created when off or when the plain clip is unknown; +Version refused; V added with no delete (V01, V02);
U replaces attach-then-remove (U01, U02); an update leaves a V alone; an update before the plain clip supersedes it; a V never supersedes; dry run sends nothing; the clip list fields for the badge;
Quick test on U (full replace in dry mode) and on V (add only); delete refused while dry. Three version-number tests were changed to 10.5.0.

## Upgrade
Replace the program files (keep `autoid.env` and `data`), restart. To use it: `VERSION_SUFFIX=on` and `BLAZE_ATTACH=dry` first; export one `_V01` and one `_U01` file for a story that is already attached; the log must show the attach (and for `_U01` the REPLACES line); then Quick test on one; then live.
