#!/usr/bin/env python3
"""v10.13.0: put the browser-scan files into the folder Storigen serves (default data/scan, or SCAN_MODEL_DIR).
No model ships with Storigen. On a machine WITH internet get two things, then run this once:
  1. the model:   pip download nudenet --no-deps   (a .whl is a zip: it holds nudenet/320n.onnx)   or   pip install nudenet   (then --nudenet finds it)
  2. the runtime: npm pack onnxruntime-web        (a .tgz: unpack it; the files are in package/dist: ort.min.js and the .wasm / .mjs files)
usage:
  python3 tools/make_scan_manifest.py --model /path/320n.onnx --ort-dir /path/package/dist [--out data/scan]
  python3 tools/make_scan_manifest.py --nudenet --ort-dir /path/package/dist
  python3 tools/make_scan_manifest.py --check            (only says what is missing)
The manifest it writes is for NudeNet's 320n model (18 labels, 320 x 320 input). Another model needs its own manifest.json: see docs/SCAN_SETUP.md."""
import argparse, json, os, shutil, sys
from pathlib import Path

LABELS = ["FEMALE_GENITALIA_COVERED", "FACE_FEMALE", "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "MALE_BREAST_EXPOSED", "ANUS_EXPOSED", "FEET_EXPOSED", "BELLY_COVERED",
          "FEET_COVERED", "ARMPITS_COVERED", "ARMPITS_EXPOSED", "FACE_MALE", "BELLY_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_COVERED", "FEMALE_BREAST_COVERED", "BUTTOCKS_COVERED"]
FLAG = ["BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "ANUS_EXPOSED", "MALE_GENITALIA_EXPOSED"]


def manifest(model_name):
    return {"name": "NudeNet 320n", "model": model_name, "input": 320, "labels": LABELS, "flag": FLAG, "threshold": 0.25, "nms_iou": 0.45, "blur_var": 60, "bgr": False}


def default_out():
    home = Path(os.getenv("AUTOID_HOME") or Path(__file__).resolve().parents[1]); return Path(os.getenv("SCAN_MODEL_DIR") or (Path(os.getenv("DATA_DIR") or home / "data") / "scan"))


def find_nudenet():
    try: import nudenet
    except ImportError: return None
    p = Path(nudenet.__file__).parent / "320n.onnx"; return p if p.is_file() else None


def check(out):
    miss = []
    mf = out / "manifest.json"
    if not mf.is_file(): miss.append("manifest.json")
    else:
        try: m = json.loads(mf.read_text(encoding="utf-8"))
        except ValueError: m = {}; miss.append("manifest.json (not valid JSON)")
        if m.get("model") and not (out / m["model"]).is_file(): miss.append(m["model"])
    if not (out / "ort.min.js").is_file(): miss.append("ort.min.js")
    if not list(out.glob("*.wasm")): miss.append("the .wasm files of onnxruntime-web")
    return miss


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model"); ap.add_argument("--nudenet", action="store_true"); ap.add_argument("--ort-dir"); ap.add_argument("--out"); ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv); out = Path(a.out) if a.out else default_out()
    if a.check:
        miss = check(out); print("scan folder: %s" % out); print("complete: the browser scan is ready" if not miss else "missing: " + ", ".join(miss)); return 0 if not miss else 1
    model = Path(a.model) if a.model else find_nudenet() if a.nudenet else None
    if not model or not model.is_file(): print("No model file. Give --model /path/320n.onnx, or install nudenet and use --nudenet."); return 2
    if not a.ort_dir or not (Path(a.ort_dir) / "ort.min.js").is_file(): print("--ort-dir must be the folder that holds ort.min.js (npm pack onnxruntime-web -> package/dist)."); return 2
    out.mkdir(parents=True, exist_ok=True); shutil.copy2(model, out / model.name); n = 0
    for f in sorted(Path(a.ort_dir).iterdir()):
        if f.name == "ort.min.js" or f.suffix in (".wasm", ".mjs"): shutil.copy2(f, out / f.name); n += 1
    (out / "manifest.json").write_text(json.dumps(manifest(model.name), indent=2) + "\n", encoding="utf-8")
    miss = check(out); print("wrote %s (%d runtime files + the model + manifest.json)" % (out, n)); print("complete" if not miss else "STILL MISSING: " + ", ".join(miss)); return 0 if not miss else 1


if __name__ == "__main__": sys.exit(main())
