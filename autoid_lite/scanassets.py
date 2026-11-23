"""v10.13.0 Browser scan: the files the page needs to run a detection model IN THE EDITOR'S BROWSER (the footage never leaves their PC).
They sit in one folder on the Storigen machine (SCAN_MODEL_DIR, default data/scan): manifest.json, the model (.onnx), ort.min.js and the .wasm files of ONNX Runtime Web.
This module only checks that the folder is complete and hands the files to a signed-in page. Nothing is uploaded, nothing is written. No model is shipped with Storigen: docs/SCAN_SETUP.md says what to put there."""
from __future__ import annotations
import json, os, re
from .common import HttpError
from .config import data_dir

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
CTYPES = {".json": "application/json", ".onnx": "application/octet-stream", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".wasm": "application/wasm"}


class Asset(bytes):
    """A file's bytes that carry their own content type and cache time (server.py reads these two attributes)."""
    ctype = "application/octet-stream"; max_age = 3600


def enabled(): return os.getenv("SCAN_ENABLED", "1") != "0"
def folder(): return os.path.realpath(os.getenv("SCAN_MODEL_DIR") or str(data_dir() / "scan"))


def status():
    """{'ready': bool, 'missing': [file names], 'name': model name}. Ready = manifest.json is valid JSON, the model file it names exists, and ort.min.js exists."""
    if not enabled(): return {"ready": False, "off": True, "missing": []}
    d = folder(); mf = os.path.join(d, "manifest.json")
    if not os.path.isfile(mf): return {"ready": False, "missing": ["manifest.json"]}
    try: m = json.load(open(mf, encoding="utf-8"))
    except (OSError, ValueError): return {"ready": False, "missing": ["manifest.json (not valid)"]}
    need = [x for x in (m.get("model"), "ort.min.js") if x]; miss = [x for x in need if not (NAME_RE.match(x) and os.path.isfile(os.path.join(d, x)))]
    if not m.get("model"): miss.insert(0, "manifest.json: 'model'")
    return {"ready": not miss, "missing": miss, "name": str(m.get("name") or m.get("model") or "")[:60]}


def read(name):
    """One file of the folder by plain name (no folders, no '..'), only the allowed kinds. 404 when it is not there."""
    if not enabled(): raise HttpError(404, "The browser scan is switched off (SCAN_ENABLED=0)")
    ext = os.path.splitext(name)[1].lower()
    if not NAME_RE.match(name or "") or ext not in CTYPES: raise HttpError(404, "no such file")
    d = folder(); p = os.path.realpath(os.path.join(d, name))
    if os.path.dirname(p) != d or not os.path.isfile(p): raise HttpError(404, "no such file")
    a = Asset(open(p, "rb").read()); a.ctype = CTYPES[ext]; return a
