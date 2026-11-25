"""v10.13.0: the browser scan. The detection itself runs in the editor's browser; the server only hands out the model files and says whether they are complete.
tools/dev/check_scan_browser.py runs the whole thing in Chromium with a stand-in model (no real model ships): the last test runs it when ffmpeg, playwright and a browser are installed."""
import json, os, pathlib, shutil, subprocess, sys, urllib.request, urllib.error
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_server import Srv
from autoid_lite import scanassets
import make_scan_manifest as msm

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
GOOD = {"name": "T", "model": "m.onnx", "input": 320, "labels": ["A", "B"], "flag": ["B"]}
def fill(d, man=GOOD, model=True, ort=True):
    d.mkdir(parents=True, exist_ok=True); (d / "manifest.json").write_text(json.dumps(man))
    if model: (d / "m.onnx").write_bytes(b"onnx")
    if ort: (d / "ort.min.js").write_text("/*ort*/")
def raw(s, path):
    rq = urllib.request.Request("http://127.0.0.1:%d%s" % (s.port, path), headers={"Cookie": s.cookie or ""})
    try:
        with urllib.request.urlopen(rq, timeout=10) as r: return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e: return e.code, e.headers, e.read()

def test_status_says_what_is_missing_and_never_pretends(tmp_path, monkeypatch):
    monkeypatch.setenv("SCAN_MODEL_DIR", str(tmp_path / "scan"))
    assert scanassets.status() == {"ready": False, "missing": ["manifest.json"]}
    d = tmp_path / "scan"; fill(d, model=False, ort=False); st = scanassets.status(); assert not st["ready"] and set(st["missing"]) == {"m.onnx", "ort.min.js"}
    fill(d); st = scanassets.status(); assert st == {"ready": True, "missing": [], "name": "T"}
    (d / "manifest.json").write_text("{not json"); assert not scanassets.status()["ready"]
    (d / "manifest.json").write_text(json.dumps({"labels": ["A"]})); assert "manifest.json: 'model'" in scanassets.status()["missing"]
    (d / "manifest.json").write_text(json.dumps({"model": "../x.onnx"})); assert not scanassets.status()["ready"], "a model name with a path is refused"
    monkeypatch.setenv("SCAN_ENABLED", "0"); assert scanassets.status() == {"ready": False, "off": True, "missing": []}

def test_the_files_are_served_only_by_plain_name_to_a_signed_in_page(tmp_path, monkeypatch):
    d = tmp_path / "scan"; fill(d); (d / "evil.exe").write_bytes(b"x"); (d / "ort-wasm.wasm").write_bytes(b"\0asm"); (tmp_path / "secret.json").write_text("{}"); monkeypatch.setenv("SCAN_MODEL_DIR", str(d))
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    st, h, body = raw(s, "/api/scan/assets/manifest.json"); assert st == 200 and h["Content-Type"] == "application/json" and json.loads(body)["model"] == "m.onnx" and "max-age" in h["Cache-Control"] and h["Cache-Control"].startswith("private")
    st, h, body = raw(s, "/api/scan/assets/ort-wasm.wasm"); assert st == 200 and h["Content-Type"] == "application/wasm" and body == b"\0asm"
    assert raw(s, "/api/scan/assets/ort.min.js")[1]["Content-Type"].startswith("text/javascript") and raw(s, "/api/scan/assets/m.onnx")[1]["Content-Type"] == "application/octet-stream"
    for bad in ("evil.exe", "nothere.onnx", "..%2Fsecret.json", "%2e%2e%2fsecret.json", "..", "a%2Fb.json", ".hidden.json"): assert raw(s, "/api/scan/assets/" + bad)[0] == 404, bad
    st, h, _ = raw(s, "/api/config"); assert h["Cache-Control"] == "no-store", "everything else is still never cached"
    s.cookie = None; assert raw(s, "/api/scan/assets/manifest.json")[0] == 401
    s2 = Srv(tmp_path, "placeholder"); s2.login(); monkeypatch.setenv("SCAN_ENABLED", "0"); assert raw(s2, "/api/scan/assets/manifest.json")[0] == 404

def test_config_tells_the_page_whether_the_scan_can_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SCAN_MODEL_DIR", str(tmp_path / "scan")); s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    c = s.call("GET", "/api/config")[1]; assert c["scan"]["ready"] is False and c["scan"]["missing"] == ["manifest.json"] and c["version"] == "11.1"
    fill(tmp_path / "scan"); c = s.call("GET", "/api/config")[1]; assert c["scan"]["ready"] is True and c["scan"]["name"] == "T"
    monkeypatch.setenv("SCAN_ENABLED", "0"); assert s.call("GET", "/api/config")[1]["scan"].get("off") is True

def test_the_setup_tool_fills_the_folder_and_checks_it(tmp_path):
    ort = tmp_path / "dist"; ort.mkdir(); (ort / "ort.min.js").write_text("x"); (ort / "ort-wasm-simd-threaded.wasm").write_bytes(b"w"); (ort / "ort-wasm-simd-threaded.mjs").write_text("m"); (ort / "README.md").write_text("no")
    mdl = tmp_path / "320n.onnx"; mdl.write_bytes(b"model"); out = tmp_path / "scan"
    assert msm.main(["--check", "--out", str(out)]) == 1
    assert msm.main(["--model", str(mdl), "--ort-dir", str(ort), "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["320n.onnx", "manifest.json", "ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm", "ort.min.js"], "only what the page needs is copied"
    m = json.loads((out / "manifest.json").read_text()); assert m["model"] == "320n.onnx" and m["input"] == 320 and len(m["labels"]) == 18 and set(m["flag"]) <= set(m["labels"]) and "FEMALE_BREAST_EXPOSED" in m["flag"] and "FACE_FEMALE" not in m["flag"]
    assert msm.main(["--check", "--out", str(out)]) == 0
    assert msm.main(["--model", str(tmp_path / "nope.onnx"), "--ort-dir", str(ort), "--out", str(out)]) == 2 and msm.main(["--model", str(mdl), "--ort-dir", str(tmp_path), "--out", str(out)]) == 2
    os.environ["SCAN_MODEL_DIR"] = str(out)
    try: assert scanassets.status()["ready"] is True, "what the tool writes is what the server accepts"
    finally: os.environ.pop("SCAN_MODEL_DIR", None)

def test_the_page_scan_code_is_read_only_local_and_never_says_clear():
    for t in ("function scanDecode(", "function scanSharp(", "function scanLetterbox(", "async function scanLoadModel(", "function scanStart(", "function scanPanel(", "🛡 Scan for nudity", "/api/scan/assets/", "NOT BLURRED?", "check by eye", "NOT cleared", "not violence"): assert t in PAGE, t
    seg = PAGE[PAGE.index("/* ---- v10.13.0 Browser scan"):PAGE.index("const insFm=")]
    for bad in ("innerHTML", 'method:"POST"', "post(", "localStorage", "lsSet(", "sendBeacon", "XMLHttpRequest", "api.groq", "FormData"): assert bad not in seg, bad
    assert seg.count("fetch(") == 0, "the only network use is api() reads of the model files and the player's own preview stream"
    for ok in ("clear", "safe", "pass"): assert ('"' + ok + '"') not in seg and ("Scan finished: nothing was flagged" in seg), ok
    assert "scanStart(id,cl||{id:id},fi||{})" in PAGE and "insBtns(x.id,x.on_nitro,x,{name:x.file,duration_s:x.duration_s})" in PAGE and "insBtns(c.id,on,c,h.file)" in PAGE
    assert PAGE.count("insBtns(c.id,on,c,h.file)") == 2, "also while the player is open: the result must not vanish"

def test_the_scan_settings_and_docs_exist():
    t = (ROOT / "autoid.env.example").read_text(encoding="utf-8"); assert "SCAN_ENABLED=1" in t and "SCAN_MODEL_DIR" in t
    d = (ROOT / "docs" / "SCAN_SETUP.md").read_text(encoding="utf-8"); assert "not cleared" in d and "Violence is not checked" in d and "make_scan_manifest.py" in d and "bgr" in d

def _browser_ok():
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")): return False
    try: from playwright.sync_api import sync_playwright
    except ImportError: return False
    try:
        with sync_playwright() as pw: pw.chromium.launch().close()
    except Exception: return False
    return True

def test_the_whole_scan_runs_in_a_real_browser_with_a_stand_in_model():
    if not _browser_ok(): pytest.skip("needs ffmpeg + playwright with a chromium browser (python -m pip install playwright; python -m playwright install chromium)")
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "dev" / "check_scan_browser.py")], capture_output=True, text=True, timeout=300, cwd=str(ROOT), env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})      # the child needs the same pytest the tests run under (it imports the test harness)
    assert "SCAN CHECK OK" in p.stdout and "FAIL " not in p.stdout, p.stdout[-2500:] + p.stderr[-800:]
