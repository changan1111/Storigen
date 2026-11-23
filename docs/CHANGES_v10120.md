# v10.12.0 - Insights: name check, clip quality check, clip frames + AI description, Insights tab

Four additions. All of them **only read**: nothing is written to Blaze, to the Nitro folder, to the project or to the database (except one event line saying who pressed a check). Quick Support is not changed.

## 1. Name check (in the Clip assistant)
A new choice **Check a file name** after you pick a story. Type or paste the name you are about to export (with or without `.mxf`). The assistant says whether the system will accept it, what it would do (replaces / adds), and if it is wrong **why**, in plain words, and gives the exact name to use with a Copy button. It catches: a wrong date or story part, one digit instead of two (`_V1`), a skipped number, a number already used, an update of a clip that does not exist (`_V02_U01` before V02), and endings that are not allowed (`_U01_V01`). Call: `GET /api/bot/checkname`. Pure rules in `coach.py`.

## 2. Insights tab (analytics)
A new **Insights** item in the left menu: today / last 7 / last 30 days. Clips, attached, **attached after the bulletin started**, updates (`_U`) and added clips (`_V`), needs desk, typical and slow (90%) time from story to attached, per bulletin and per day, and the slowest clips. Everything comes from the timestamps the registry already keeps. It groups by bulletin and day, not by person. Call: `GET /api/analytics?days=`.

## 3. Quality check (button on a clip on Nitro)
**🔍 Check quality** reads the file once with ffmpeg and tells: black picture (start/end and middle), frozen picture, silence, loudness (LUFS) and peaks, 16:9 shape, no picture / no sound track, and a length different from what is attached in the story. Green / amber / red with plain sentences. Low priority, one clip at a time (`QUALITY_MAX_JOBS`), stopped after `QUALITY_MAX_SECONDS`. Nothing stored. Limits can be changed in `autoid.env`. Call: `GET /api/clips/<id>/quality`.

## 4. Frames and AI description (buttons on a clip on Nitro)
* **🖼 Frames**: 4 small pictures spread over the clip. Made in memory, shown, forgotten. Nothing leaves the server.
* **✨ Describe with AI** (only when `GROQ_API_KEY` is set): sends those few small pictures to **Groq** (an outside service) and shows one sentence and a few tags. The page asks for confirmation the first time. The prompt tells the model not to name anyone. The answer is shown with "check it before you rely on it". If Groq is down or the key is wrong, the pictures still show with the reason.
* The key lives only in `autoid.env`. It is never sent to the browser, never logged and never in an error message. A ceiling (`GROQ_MAX_PER_HOUR`, default 60) protects the key. Calls: `GET /api/clips/<id>/frames?ai=0|1`.
* The model name is a setting (`GROQ_VISION_MODEL`): Groq changes its list. If the description says the model cannot be used, choose a current vision model at console.groq.com/docs/vision.

## New settings (autoid.env.example)
`QUALITY_*`, `CLIP_FRAMES`, `CLIP_FRAMES_COUNT`, `GROQ_API_KEY`, `GROQ_VISION_MODEL`, `GROQ_MAX_PER_HOUR`, `CLIP_SUMMARY=0` (switch the AI button off).

## Tested
`tests/test_insights.py`: 23 tests (name rules, ffmpeg log parsing and verdicts, real ffmpeg on generated clips, the guards, Groq request / error mapping with a stand-in, key never exposed, analytics numbers, page wiring). The whole suite: 573 passed; the two failures that were already there on v10.11.0 (`test_report_classes_without_a_server`, `test_the_switch_and_the_missing_ffmpeg_are_reported`) are unchanged. The real page was also driven in Chromium against a live server (buttons, panels surviving the 5-second refresh, pictures loading, Insights tab, assistant name check). **Not tested here:** the live call to Groq (no internet in the build machine) and a real Nitro MXF from your encoder: try both once on your server.
