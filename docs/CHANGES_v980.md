# v9.8.0 (NewsFusion final)

Everything of v9.7.5 plus the attached-clip facts.

## Attached clip: media object, item and duration on the dashboard
Once a clip is attached, the dashboard shows what Blaze holds for it:

* **MOS object** (mosObjectId): the Blaze media object of the attached clip.
* **Item** (itemId): the story item the clip sits on.
* **Duration**: the clip length in the story, `m:ss (N s)`. Whole seconds, rounded down, exactly what the attach sends.

Where: the **story card** (small chips under the four-step strip; click a chip to copy it), the **details panel** (MOS object ID, Item ID, Clip duration, Blaze clip ID) and the **history** line "Attached (...)". Before the attach only the media object is shown, in grey, once it was found in Blaze's media list. The **CSV export** has four new columns (MOS object ID, Item ID, Duration (s), Blaze clip ID) and the **search** finds a clip by its MOS object ID or item ID.

How they are recorded:
* **Live attach by the tool:** from the attach itself and the read-back of the story (the clip as Blaze returns it).
* **Desk attach:** the poller's read-back of the story records them when it marks the clip ATTACHED.
* **Clips attached before this version** (or marked attached by hand): the next read-back fills in what is missing. A recorded value is never overwritten, a wrong story records nothing, and the state is never changed by the fill-in.

Database: three new columns on `clip_ids` (`item_id`, `attach_dur`, `blaze_clip_id`), added automatically at start; the mosObjectId uses the existing `media_id`.

New endpoint field: `POST /svc/attach/confirm` accepts `mos_object_id`, `item_id`, `duration_s`, `blaze_clip_id` (all optional).

Tests: `tests/test_attached_clip_facts.py` (9 tests: live attach, desk attach, backfill, wrong story, CSV, search, history, dashboard).
