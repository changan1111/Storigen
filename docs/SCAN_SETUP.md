# Browser scan for unblurred nudity (v10.13.0): setup and honest limits

The **🛡 Scan for nudity** button plays the clip in the editor's own browser at double speed (the normal Play preview) and looks at one frame every second with a detection model that runs **inside that browser**. The footage is not uploaded anywhere and nothing is stored: not on the server, not in the database.

## What it is, and what it is not
* It flags **exposed** nudity it can recognise. For each flag it shows the frame (with a red box), the time, the model's confidence and a **sharpness number** for that area. High sharpness is shown as **NOT BLURRED?**. Low sharpness is shown as *looks soft or blurred: check by eye*. A very small area is shown as *too small to judge*. Nothing is ever hidden or dismissed by the page: a person decides.
* **A clip with no flags is not cleared.** The model can miss things; it sees the low-resolution preview (about 360p) of a frame each second; a properly blurred area usually hides the very features the model looks for, which is the outcome you want, but it also means an under-blurred area can slip through.
* **Nudity only. Violence is not checked** (no reliable gore model runs in a browser). That needs Groq or a person, planned for the server-side check.
* It only scans while someone watches. Keep the tab in front. Nothing runs by itself when a clip reaches Nitro (that is the later server-side check).
* The sharpness threshold (`blur_var`, default 60) is a starting guess. Calibrate it on your own blurred and unblurred clips: the flag shows the measured number.

## Install (once, on a machine with internet)
No model ships with Storigen, because the files are large and you should choose and approve the model your newsroom uses.
1. **Model** (the tool below is written for NudeNet 320n, an open-source detector): `pip download nudenet --no-deps` and unzip the `.whl` (it is a zip) to find `nudenet/320n.onnx`; or `pip install nudenet`.
2. **Runtime** (ONNX Runtime Web): `npm pack onnxruntime-web`, unpack the `.tgz`; the files are in `package/dist` (`ort.min.js` and the `.wasm` / `.mjs` files).
3. Run: `python3 tools/make_scan_manifest.py --model 320n.onnx --ort-dir package/dist` (or `--nudenet`). It fills `data/scan` (or `SCAN_MODEL_DIR`) and writes `manifest.json`. `--check` lists what is missing.
4. Reload the dashboard. The button turns on by itself when the folder is complete. Until then it is greyed out and says why.

Check each model's licence before newsroom use. A different model needs its own `manifest.json`:
`{"name": "...", "model": "file.onnx", "input": 320, "labels": [...in the model's class order...], "flag": ["the labels to flag"], "threshold": 0.25, "nms_iou": 0.45, "blur_var": 60, "bgr": false}`
(YOLOv8-style output, channels first or last, is understood; if the number of labels does not match the model, the page says so.)

## First thing to do on your server: test it on clips you know
Storigen's own tests prove everything around the model (files served, loading, frame grabbing, the maths that places boxes, the sharpness measure, flags and pictures, the wording) with a stand-in model, **not** that a real model finds real content, because no model was available to the build machine. So:
1. Scan a few clips you know contain unblurred nudity, a properly blurred version, and ordinary clips.
2. If a known clip is not flagged at all, try `"bgr": true` (colour order) and a lower `threshold` (0.15 to 0.2).
3. Note the sharpness numbers of blurred and unblurred flags and set `blur_var` between them.

## Settings
`SCAN_ENABLED=0` removes the button. `SCAN_MODEL_DIR` moves the folder. The scan needs the Play preview to work (ffmpeg and `PREVIEW_ENABLED=1`).
