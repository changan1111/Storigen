# Short checks to run on your real systems (do them in this order)

Each one is a few minutes on a TEST rundown. Do not use a live bulletin.

## 1. Does your Blaze have a usable Placeholder? (decides LINK_MODE)
In a test story: Media Search > Placeholder.
* Is the **Media Slug** box editable? Does it fill with a number by itself?
* Type `TEST_0001_SLUG`, choose Video, Save: a red clip should appear in the story.
* Put a tiny file with exactly that name through Playout to Nitro. Does the red clip turn green **by itself**, or only after you click the paperclip in Media Search > Playout? Does the paperclip attach to the placeholder, or add a second clip?
Result: Media Slug editable + links by name = `LINK_MODE=placeholder` works. Otherwise use the Playout-tab attach (desk), which works in both modes.

## 2. Does the MXF on Nitro keep the ID?
Export a test file named `20261105_0001U_TEST.mov` to Playout. When the converted file lands on Nitro, does its name still START with `20261105_0001U`? (The watcher matches on date + number.)

## 3. Does the watcher see the "done" signal?
`python3 autoid.py doctor` shows the folders. Create an ID, drop the file in `INBOX/NEWS`, let your job convert it. The page should show EXPORTING, then ON_NITRO. If it goes to NEEDS_DESK, read the reason on the row.

## 4. (story_id mode only) What does Blaze send?
Run `python3 tools/mos_sniffer.py` on a spare PC, add that PC as a MOS device in a TEST Blaze (ports 10540/10541), send a test rundown, then edit a slug, move a story, delete a story. In `mos_capture.log` look for `<roID>`, `<storyID>`, `<storySlug>`. Pass = the story ID is the same after an edit and a move.
