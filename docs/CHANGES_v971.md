# v9.7.1: clip name DDMMYY_STORY_NAME, shared by repeated stories

**The clip name** (what the editor puts on the file, what Nitro keeps, what Blaze shows) is `DDMMYY_STORY_NAME`, e.g. `111126_FIRE_ON_BEACH`, up to 100 characters of name. A title with no usable letters (for example only Tamil) becomes `DDMMYY_S<story number>`.

**One clip for a repeated story.** Every story with the same name on the same day shares the same clip name, so one exported file serves all of them. Each Blaze story still has its **own internal ID** (date, daily number, check letter, e.g. `20261111_1185G_FIRE_ON_BEACH`), shown under *View details*. The file event (Playout, Nitro) is applied to every story that shares the name; each story is attached and read back by itself.

**Versions go by show.** *+ Version* now asks: *this show only* or *this show and later shows* (the shows that start at or after this one and hold the same story, still at the same version). Earlier, already aired shows keep their clip. New versions are named `111126_FIRE_V2`, `_V3`. The desk or the poller (auto) attaches them as before.

**Delete version** (card button, only for version 2 or higher that is still *waiting for clip*): same this-show / later-shows choice. A version is refused once a file was seen for it or it was sent to Blaze or attached; version 1 can never be deleted. The deletion is written to the event log. The next *+ Version* reuses the number.

**No auto attach for montages.** `BLAZE_NO_AUTO_ATTACH=OPENING MONTAGE,END MONTAGE` (default): these stories get an ID and stay in the tracker, but the poller never attaches them; the desk does. (The poller still reads Blaze back and marks them attached when the desk has done it.)

**Database:** one new column `clip_ids.name_id` (added automatically at start, existing IDs untouched; for old rows the name is their old ID). `ID_FORMAT=legacy` switches back to `YYYYMMDD_NNNNC_NAME` for new stories.

**Check on one real clip first:** the Nitro MXF and the Blaze media title must carry the clip name exactly (capitals and extension do not matter).

Changed files: `autoid_lite/ids.py`, `db.py`, `server.py`, `watcher.py`, `gateway.py`, `web/index.html`; `tools/blaze_poll.py`; `autoid.py`; `autoid.env.example`; tests (`test_clip_names_and_versions.py` new, six older test files pin `ID_FORMAT=legacy`).
