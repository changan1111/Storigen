# v10.9.3 - PROGRAMS, PROMOS and ADS files are found and attached (the media list is read per group)

**Why:** on the real system a NEWS clip was found in Blaze's media list and attached, but a clip exported to PROGRAMS (file `191126_program vis clip check.mxf`, `objGroup` PROGRAMS, `UPDATED`, 20 s) was never found: its story showed `READY ON NITRO` and then no `GOING TO ATTACH` line for 20 minutes. Blaze's plain media list (no group named) holds only the NEWS group, so a file of another group was never in it.

## What changed
* The poller reads the media list once as before, then **once per group** (`BLAZE_MEDIA_GROUPS`, default `NEWS,PROGRAMS,PROMOS,ADS`), naming the group in the filter field `BLAZE_MEDIA_GROUP_KEY` (default `objGroup`). Files are de-duplicated by id and matched exactly as before; nothing else about attaching changed (same checks, same one attempt per clip, same scope and kill switch).
* **Self-protecting:** if Blaze answers a group query with files of other groups, the filter field is not known to it: that group is marked IGNORED, not asked again, and the log says `WARNING: group list(s) ... not used ... Run: python3 tools/blaze_poll.py groups`. A group that fails (3 times in a row) is switched off the same way. One failing group never hides the others. An expired session still propagates as before.
* The log gets one line when the group counts change: `media list by group: NEWS 140 files, PROGRAMS 6 files, ...`.
* Title search (`BLAZE_MEDIA_MODE=search`, and the fallback of list mode): when the plain search finds nothing, the same search is made inside each group.
* New command `python3 tools/blaze_poll.py groups`: tries each possible filter field (`objGroup`, `group`, `objgroup`, `mediaGroup`) for each group and prints the number of files, so you can see which field your Blaze accepts. `python3 tools/blaze_poll.py media [text]` now lists every group.
* `BLAZE_MEDIA_GROUPS=NONE` = the old behaviour (plain list only).

## Not verified against a live Blaze
The filter field name `objGroup` is the name of the field in the media records; it is the most likely filter name but it was **not** captured from the Blaze page. Run `python3 tools/blaze_poll.py groups` once after the upgrade. If no key shows per-group counts, copy the `mosobjects` request the Blaze page sends when you open its PROGRAMS tab (DevTools > Network) and set `BLAZE_MEDIA_GROUP_KEY` to the field it uses.

## Tests
`tests/test_media_groups.py`: 8 tests (default and `NONE`, a PROGRAMS file found only through the group list and not without it, PROMOS and ADS and the group named in the request, a Blaze that ignores the field, a failing group, the title-search fallback, the command). The fake Blaze of `tests/test_blaze_poll.py` can now keep NEWS in the plain list. Suite: 471 passed; `test_preview.py::test_the_switch_and_the_missing_ffmpeg_are_reported` fails the same way on v10.9.2 in the build sandbox (a Nitro path check) and is unrelated.

## Upgrade
Back up `data`, replace the program files (keep `autoid.env` and `data`), restart (`./restart_autoid.sh`), Ctrl+F5 once; the page header must say v10.9.3. Optionally add to `autoid.env`: `BLAZE_MEDIA_GROUPS=NEWS,PROGRAMS,PROMOS,ADS` and `BLAZE_MEDIA_GROUP_KEY=objGroup` (they are the defaults). Then run `python3 tools/blaze_poll.py groups`, and look for `media list by group:` in the poller log.
