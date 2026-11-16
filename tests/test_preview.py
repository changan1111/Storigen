"""v10.1.0: Play from Nitro. The file is converted on the fly and streamed; nothing is stored. Needs ffmpeg for the streaming tests."""
import os, pathlib, shutil, subprocess, sys, urllib.request, urllib.error
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from test_server import Srv

ROOT = pathlib.Path(__file__).resolve().parents[1]
FF = shutil.which("ffmpeg")

def mxf(path, secs=2):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=%d:size=640x360:rate=25" % secs, "-f", "lavfi", "-i", "sine=duration=%d" % secs,
                    "-c:v", "mpeg2video", "-c:a", "pcm_s16le", "-ar", "48000", "-f", "mxf", str(path)], check=True)

def clip_on_nitro(s, nitro_path, story="Fire on beach"):
    c = s.call("POST", "/api/manual", {"rundown": "14:00 Bulletin", "story": story})[1]
    with s.app.db.tx() as cur: cur.x("INSERT INTO files(clip_id,nitro_path,state,created_at) VALUES(?,?,?,?)", (c["id"], str(nitro_path), "ON_NITRO", "2026-11-15T10:00:00+05:30"))
    return c

def get(s, cid):
    rq = urllib.request.Request("http://127.0.0.1:%d/api/clips/%d/preview" % (s.port, cid), headers={"Cookie": s.cookie or ""})
    try:
        with urllib.request.urlopen(rq, timeout=30) as r: return r.status, r.headers.get("Content-Type"), r.headers.get("Content-Length"), r.read()
    except urllib.error.HTTPError as e: return e.code, e.headers.get("Content-Type"), None, e.read()

@pytest.mark.skipif(not FF, reason="ffmpeg is not installed")
def test_a_nitro_mxf_streams_as_a_playable_mp4_and_leaves_nothing_behind(tmp_path):
    nitro = tmp_path / "ONAIR" / "Nov-26" / "15-11-2026"; nitro.mkdir(parents=True); f = nitro / "20261115_0001_FIRE.mxf"; mxf(f)
    os.environ["NITRO_DIR"] = str(tmp_path / "ONAIR")
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; c = clip_on_nitro(s, f); before = sorted(p.name for p in tmp_path.rglob("*") if p.suffix != ".db" and "t.db" not in p.name)
    st, ct, cl, body = get(s, c["id"]); assert st == 200 and ct == "video/mp4" and cl is None and body[4:8] == b"ftyp", (st, ct, body[:60])
    out = tmp_path / "got.mp4"; out.write_bytes(body); p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
    assert "h264,360" in p.stdout and "aac" in p.stdout, p.stdout + p.stderr
    out.unlink(); after = sorted(p.name for p in tmp_path.rglob("*") if p.suffix != ".db" and "t.db" not in p.name); assert before == after, "nothing is written anywhere"

def test_login_is_required_and_a_clip_not_on_nitro_says_so(tmp_path):
    os.environ["NITRO_DIR"] = str(tmp_path); s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; c = s.call("POST", "/api/manual", {"rundown": "14:00 Bulletin", "story": "X"})[1]
    st = get(s, c["id"])[0]; assert st == 404
    s.cookie = None; assert get(s, c["id"])[0] == 401

def test_a_file_outside_the_nitro_folder_is_never_streamed(tmp_path):
    (tmp_path / "ONAIR").mkdir(); other = tmp_path / "secret.mxf"; other.write_bytes(b"x" * 100); os.environ["NITRO_DIR"] = str(tmp_path / "ONAIR")
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; c = clip_on_nitro(s, other); st, ct, _, body = get(s, c["id"]); assert st == 403 and b"outside" in body
    c2 = clip_on_nitro(s, tmp_path / "ONAIR" / ".." / "secret.mxf", "Second story"); assert get(s, c2["id"])[0] == 403

def test_a_missing_file_and_a_second_preview_get_a_clear_message(tmp_path):
    (tmp_path / "ONAIR").mkdir(); os.environ["NITRO_DIR"] = str(tmp_path / "ONAIR"); s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    c = clip_on_nitro(s, tmp_path / "ONAIR" / "gone.mxf"); st, _, _, body = get(s, c["id"]); assert st == 404 and b"not reachable" in body
    sys.path.insert(0, str(ROOT)); from autoid_lite import preview
    os.environ["PREVIEW_MAX_JOBS"] = "1"; sem = preview._slot(); assert sem.acquire(blocking=False)
    try:
        f = tmp_path / "ONAIR" / "a.mxf"; f.write_bytes(b"x"); c2 = clip_on_nitro(s, f, "Another story"); st, _, _, body = get(s, c2["id"]) if FF else (429, 0, 0, b"")
        assert st == 429 and (b"Another preview" in body or not FF)
    finally: sem.release()

def test_the_switch_and_the_missing_ffmpeg_are_reported(tmp_path):
    sys.path.insert(0, str(ROOT)); from autoid_lite import preview; from autoid_lite.common import HttpError
    os.environ["PREVIEW_ENABLED"] = "0"
    try: preview.open_stream("x"); assert False
    except HttpError as e: assert e.status == 404 and "switched off" in e.detail
    os.environ["PREVIEW_ENABLED"] = "1"; os.environ["PREVIEW_FFMPEG"] = ""; old = shutil.which
    shutil.which = lambda n: None
    try:
        try: preview.open_stream("x"); assert False
        except HttpError as e: assert e.status == 503 and "ffmpeg" in e.detail
    finally: shutil.which = old; os.environ.pop("PREVIEW_FFMPEG", None)

def test_the_page_has_the_play_button_and_closes_the_stream_when_you_leave():
    h = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    assert "▶ Play from Nitro" in h and '"/api/clips/"+c.id+"/preview"' in h and "if(!same)stopPreview()" in h and 'removeAttribute("src")' in h
    assert "cache" not in h[h.index("function previewBox("):h.index("async function showDetail(")].lower()

def test_nothing_in_the_preview_code_writes_a_file():
    import re; s = (ROOT / "autoid_lite" / "preview.py").read_text(encoding="utf-8")
    assert not re.search(r"\bopen\(|tempfile|mkdtemp|write_bytes|makedirs|\"-y\"", s), "the preview must never write a file"
