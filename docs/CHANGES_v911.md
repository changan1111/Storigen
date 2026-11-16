# v9.11 (Storigen)

Everything of v9.8.1 plus the fixes from the 13 Nov field test.

* **Shared stories:** a story that sits in several bulletins has one clip ID per bulletin (same clip name). The read-back marked only the first of them as attached; the others stayed WAITING_FOR_CLIP and were listed OVERDUE in the report for ever (13 of 28 on 13 Nov, although the poller logged "already in story: nothing to do"). Now every clip ID of that story and name is recorded and confirmed, each with its own bulletin. A file attached twice in the story is still reported as DUPLICATE. Tests: `tests/test_shared_story_siblings.py`.
* **Read-back without the NAS watcher:** with `BLAZE_ATTACH_WHEN=media` the read-back of Blaze confirms clips that are still WAITING_FOR_CLIP (the NAS watcher never moved them). The server accepts this only from source `blaze_readback` with `media_mode` exactly `true`; the other checks (right story, right bulletin, story not removed) are unchanged. In `watcher` mode nothing changes.
* **`blaze_poll.py report` / `shows`:** the day may be typed as 20261113, 2026-11-13, 13112026 or 13-11-2026; anything else is one clear line instead of a traceback.
* **ATTACHMENT CHANGED** log lines show the clip status, so READY -> ON AIR -> DONE is visible (all 159 lines of the 13 Nov log looked identical before).
* **Tests:** the old test that expected live attach to wait for the NAS watcher now runs in `BLAZE_ATTACH_WHEN=watcher`; a new test covers attaching in `media` mode with the NAS not mounted (`WAITING_FOR_CLIP` and `EXPORTING`).
* **Docs:** `BLAZE_ATTACH_WHEN` is in `autoid.env.example` and the README.
* **Version:** `/api/config` and `/health` report `9.11`.

## Not changed (by design, say so before go-live)
* Live attach covers verified story formats 20 and 21 only; other formats (Package, HeadLines, Montage) stay with the desk.
* Linked stories (one story in several shows) are never attached by the tool; the desk does them and the read-back now records all their clip IDs.
* `_V2`+ versions: `BLAZE_VERSION_MODE=desk`.
* Run only ONE poller per Blaze user (a second login replaces the first one's session; seen 5 times on 13 Nov).
* Not yet seen on a real Blaze: a live attach. Do the QUICKTEST on one story first.
