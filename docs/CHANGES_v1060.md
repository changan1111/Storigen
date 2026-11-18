# v10.6.0 - Story Media Gallery: a story with several clips shows them all as one card in the Media & IDs pane

**Request:** when a story has more than one clip (the plain clip plus `_V01` additions and `_U01` updates), the Media & IDs pane should show all of them together, as one card, instead of one clip at a time.

## What the desk sees
* A story with **two or more clip IDs** gets a **Story Media Gallery** card at the top of the Media & IDs pane: story name and Blaze story ID, a "3 clips" pill, then one row per clip.
* Each row: a video tile with the clip length, the label (**BASE**, **V01**, **U01**; an old numbered version shows **V2**), the full clip name, **MOS** and **Item**, a role chip (**Original** / **Additional** / **Update**, the newest of several updates says "latest"), the clip's state, and **▶ Play preview**.
* The clip that is open below (its Media ID, IDs, Quick test, history) is marked **Open** with an accent bar. A click on another row opens that clip; the IDs and buttons below follow.
* **Play preview** works on every row. There is still one player for the pane: starting another clip's preview stops the one playing, and the player sits inside the row it belongs to. Nothing is stored (same stream as Play from Nitro). The button is greyed until the clip's file is on Nitro.
* A story with **one clip** looks exactly as before (the single Preview box, no gallery).
* A row whose clip is not in the current list (a filter, search or page hides it) cannot be opened from the gallery and says so; Play preview still works on it.
* Phone and narrow windows: the same card, with a narrower tile.

## Under the hood
* `GET /api/clips/<id>/history` now also returns `story_clips`: every clip ID of the same story (same bulletin), the plain clip first, then the others in the order they were created, each with `label`, `role`, `state`, `mos_object_id`, `item_id`, `attach_dur`, `blaze_clip_id`, `on_nitro`, `duration_s` and `file`. Works with `VERSION_SUFFIX` on or off. Same login rule as the history. No database change, no new setting.
* `index.html`: new `gallery()`; the preview player moved out of `previewBox()` into `startPreview(c, f)` so the gallery rows and the single box share it.
* `tools/standalone_shim.js`: the first sample story now has three clips (BASE, `_V01` attached, `_U01` ready), so `python3 tools/make_standalone.py --out demo.html` shows the gallery.

## Not included
* **Real picture thumbnails.** The tile is a coloured placeholder with the length. A real frame would need ffmpeg to grab one picture per clip each time the pane opens, which goes against "nothing stored, light on the system". It can be added as an on-demand, one-slot call if wanted.
* The shared-story case (the same Blaze story in several bulletins) lists the clips of the open bulletin's story only, as before.

## Tests
`tests/test_story_media_gallery.py` (10 tests): the list for three clips and its order, the same list from every clip of the story, a second story kept out, old numbered versions, login required, the page checks (gallery only for several clips, what the card holds, rows outside the list, one player, the sample data), and a real ffmpeg stream of an added clip's own file.
`autoid_lite/preview.py` was an empty file in the first zip; it is restored here from the original file, unchanged. With it, all of `tests/test_preview.py` passes (the 4 failures noted in v10.5.0 are gone). Whole suite: 422 passed, 1 skipped (needs jsdom).

## Upgrade
Replace `autoid_lite/api_dashboard.py`, `autoid_lite/preview.py` and `autoid_lite/web/index.html`, restart the web service, Ctrl+F5 once. Keep `autoid.env` and `data`.
