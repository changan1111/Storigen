# v10.13.0 - Browser scan: flag unblurred nudity while the clip plays (the model runs in the editor's browser)

## What it adds
A **🛡 Scan for nudity** button next to **Check quality / Frames** on a clip that is on Nitro. It plays the clip in the normal Play preview at double speed (muted) and looks at one frame every second with a detection model that runs **inside the editor's browser** (ONNX Runtime Web, WebAssembly). **The footage is not uploaded anywhere and nothing is stored**: no file, no database row, no event line.

Each detection becomes a **flag** with the frame (red box), the time range, the model's confidence, and a **sharpness number** of that area (variance of the Laplacian on a 64 x 64 grey copy):
* sharp area: **NOT BLURRED?** (red)
* soft area: *looks soft or blurred: check by eye* (amber)
* very small area: *too small to judge: check by eye* (amber)
Every flag is listed whatever its verdict: the page never dismisses a detection. **▶ go to** moves the player to that moment (within what the player has already received). Up to 40 flags; more are reported as "look at the clip".

## What it is not (also written in the panel)
* A clip with no flags is **not cleared**. The finished panel says so every time, and says how much of the clip was scanned (if the player was closed early, only that part).
* **Nudity only. Violence is not checked.** No reliable gore model runs in a browser; that belongs to the later server-side check (Groq).
* It runs only while someone watches, with the tab in front. Nothing runs by itself when a clip reaches Nitro (also for the later server-side check).
* It sees the low-resolution preview (about 360p), one frame per second.

## No model ships with Storigen
The button is greyed out, with the reason, until the folder `data/scan` (or `SCAN_MODEL_DIR`) holds `manifest.json`, the model and ONNX Runtime Web. `tools/make_scan_manifest.py` fills it (written for NudeNet 320n); `docs/SCAN_SETUP.md` has the steps, the licence reminder, how to use another model, and **how to test it on clips you know**. The server only serves those files to a signed-in page (`GET /api/scan/assets/<name>`: plain file names, allowed kinds only, cached by the browser for an hour; every other response is still never cached). `SCAN_ENABLED=0` removes the button.

## Tested, and what is not
`tests/test_scan.py` (7 tests; the last runs `tools/dev/check_scan_browser.py`): the folder status and guards, the setup tool, the page code (read-only, no network use of its own), and the whole scan in real Chromium on the real Play-preview stream, with a **stand-in model**: asset loading, letterbox maths, decoding and NMS (channels first and last), the manifest-mismatch message, the sharpness measure (textured 20,000, the same texture blurred 4, flat 0), two flags at the right times with the right verdicts, pictures kept in memory only, the "not clearance" wording, "go to", nothing written anywhere. Whole suite: 580 pass; the 2 failures present since v10.11.0 are unchanged.
**Not tested:** a real model. None was available to the build machine (no internet), so whether a real model finds real content, the colour order (`bgr`, believed RGB for NudeNet) and a good `blur_var` for your footage are for you to check on known clips, as `docs/SCAN_SETUP.md` explains. Also untested: ONNX Runtime Web itself loading its `.wasm` files from the Storigen server (the stand-in replaces it).
