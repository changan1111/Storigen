# v10.9.2 - a story renamed in Blaze: the row is updated, not struck out (new story ID in the same slug)

**Why:** v10.9.1 fixed a rename where Blaze keeps the same story ID. On the real system the old story showed **struck out** (removed) after a rename: Blaze gives the renamed story a **new story ID in the same rundown slug**. v10.9.0 and v10.9.1 then struck out the old row and made a second row with a new clip ID; the old row was never "updated".

## What happens now
* When a story ID Storigen does not know takes over a slug (same slug ID, same bulletin) that holds a story which is no longer listed, **and every clip of that old story is still WAITING_FOR_CLIP** (no file seen, nothing sent), the old row is **kept**: it moves to the new story ID, keeps its clip ID (internal ID unchanged), and the title change that comes with it gives the clip the new name (v10.9.1 logic; `_U01` / `_V01` endings follow). No strike-out, no second row. The desk gets the same "Story renamed in Blaze" alert; the event log gets `story_id_changed` and `story_renamed`.
* Everything else behaves as before (struck out + a new row): the old clip already has a file / is on Nitro / attached; the new story ID has no slug ID; the slug held two candidates; the old story is still listed in the slug.
* Same Blaze story ID with a new title (v10.9.1): unchanged.
* A title with no Latin letters (the name is `DDMMYY_S<story id>`) follows too.

## Tests
`tests/test_story_rename.py`: 15 tests (9 from v10.9.1 + 6 new: new ID in the same slug, a clip that already has its file, no / different slug ID, a story still listed is never adopted, a non-Latin title, and the real poller end to end). With the adoption switched off, 3 of them fail.

## Upgrade
Back up `data`, replace the program files (keep `autoid.env` and `data`), restart both services, Ctrl+F5 once; the page header must say v10.9.2. No settings, no database change beyond v10.9.1's small table.
