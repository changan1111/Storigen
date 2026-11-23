"""v10.18.0: a clip added with the + (Add media) button shows on the dashboard at once and has a Play preview.
Before: it appeared only after the poller's next full report, the story card showed nothing about it unless VERSION_SUFFIX=on, and its card said 'No preview'.
Now: the finished Support add puts the clip in the story's list itself; the card shows it for every setting; Play looks the file up on Nitro BY NAME every time (nothing stored)."""
import json, os, pathlib, shutil, subprocess, sys, urllib.request, urllib.error
import pytest
from test_server import Srv

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
FF = shutil.which("ffmpeg")
from autoid_lite import preview
from autoid_lite.common import HttpError


def mxf(path, secs=2):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=%d:size=640x360:rate=25" % secs, "-f", "lavfi", "-i", "sine=duration=%d" % secs,
                    "-c:v", "mpeg2video", "-c:a", "pcm_s16le", "-ar", "48000", "-f", "mxf", str(path)], check=True)


def day_folder(root, pat="%b-%y/%d-%m-%Y", k=0):
    import datetime as dt
    d = pathlib.Path(root) / (dt.date.today() + dt.timedelta(days=k)).strftime(pat); d.mkdir(parents=True, exist_ok=True); return d


@pytest.fixture
def nitro(tmp_path, monkeypatch):
    root = tmp_path / "ONAIR"; root.mkdir()
    for k, v in (("NITRO_DIR", str(root)), ("NITRO_DATE_PATH", "%b-%y/%d-%m-%Y"), ("NITRO_EXTS", ".mxf"), ("NITRO_SCAN_DEPTH", "3"), ("NITRO_SCAN_DAYS_BACK", "1"), ("NITRO_SCAN_DAYS_AHEAD", "1")): monkeypatch.setenv(k, v)
    return root


# ---------- the lookup of a file by the clip's name ----------
def test_the_file_is_found_by_name_in_todays_folder_and_below(nitro):
    d = day_folder(nitro); (d / "NEWS").mkdir(); f = d / "NEWS" / "231126_Fire on beach_V01.mxf"; f.write_bytes(b"x")
    for title in ("231126_FIRE_ON_BEACH_V01", "231126 fire-on-beach V01", "231126_Fire on beach_V01.mxf"):
        p, where = preview.find_nitro_file(title); assert p == str(f), (title, p, where)

def test_the_closest_day_wins_and_far_days_are_not_searched(nitro):
    today, yday, old = day_folder(nitro), day_folder(nitro, k=-1), day_folder(nitro, k=-5)
    (old / "A_V01.mxf").write_bytes(b"x"); assert preview.find_nitro_file("A_V01")[0] is None, "5 days back is outside NITRO_SCAN_DAYS_BACK"
    (yday / "A_V01.mxf").write_bytes(b"x"); assert preview.find_nitro_file("A_V01")[0] == str(yday / "A_V01.mxf")
    (today / "A_V01.mxf").write_bytes(b"x"); assert preview.find_nitro_file("A_V01")[0] == str(today / "A_V01.mxf"), "today first"

def test_no_match_says_where_it_looked_and_other_names_never_match(nitro):
    d = day_folder(nitro); (d / "A_V01_FINAL.mxf").write_bytes(b"x"); (d / "A_V01.mov").write_bytes(b"x"); (d / ".A_V01.mxf").write_bytes(b"x")
    p, where = preview.find_nitro_file("A_V01"); assert p is None and pathlib.Path(d).name in where
    assert preview.find_nitro_file("")[0] is None

def test_without_day_folders_the_whole_nitro_folder_is_searched_and_a_missing_folder_is_reported(tmp_path, monkeypatch):
    root = tmp_path / "ONAIR"; (root / "x").mkdir(parents=True); (root / "x" / "B.mxf").write_bytes(b"x"); monkeypatch.setenv("NITRO_DIR", str(root)); monkeypatch.setenv("NITRO_DATE_PATH", "")
    assert preview.find_nitro_file("B")[0] == str(root / "x" / "B.mxf")
    monkeypatch.setenv("NITRO_DIR", str(tmp_path / "nope"))
    try: preview.find_nitro_file("B"); assert False
    except HttpError as e: assert e.status == 404 and "not reachable" in e.detail
    monkeypatch.setenv("NITRO_DIR", "")
    try: preview.find_nitro_file("B"); assert False
    except HttpError as e: assert e.status == 503


# ---------- the server ----------
def story(tmp_path):
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    assert s.svc("POST", "/svc/stories", {"blaze_rundown_id": "RO1", "blaze_story_id": "740371", "slug": "KARTHIK CLIP CHECK", "rundown_name": "21:30 Bulletin"})[0] == 200
    with s.app.db.tx() as cur:
        cid = cur.q("SELECT c.id FROM clip_ids c JOIN stories st ON st.id=c.story_id WHERE st.blaze_story_id='740371' ORDER BY c.id")[0]["id"]
        cur.x("UPDATE clip_ids SET state='ATTACHED', media_id='1126526', blaze_clip_id='957411' WHERE id=?", (cid,))
    return s, cid

def queue_add(s, mos="1126999", name="231126_KARTHIK_V01"):
    with s.app.db.tx() as cur:
        return cur.insert("""INSERT INTO support_jobs(kind,state,by_user,created_at,updated_at,expires_at,blaze_rundown_id,rundown,blaze_story_id,story,media_id,media_name) VALUES('ADD','WORKING','editor',?,?,?,?,?,?,?,?,?)""",
                          ("2026-11-23T10:00:00Z", "2026-11-23T10:00:00Z", "2099-01-01T00:00:00Z", "RO1", "21:30 Bulletin", "740371", "KARTHIK CLIP CHECK", mos, name))

def test_a_finished_add_shows_on_the_dashboard_at_once_without_a_poller_report(tmp_path, monkeypatch):
    monkeypatch.delenv("VERSION_SUFFIX", raising=False)                      # the default: OFF. The story card used to show nothing for an added clip in this setting
    s, cid = story(tmp_path); j = queue_add(s)
    assert [x["role"] for x in s.call("GET", "/api/clips/%d/history" % cid)[1]["story_clips"]] == ["original"]
    r = s.svc("POST", "/svc/support/result", {"id": j, "state": "DONE", "message": "Attached", "result": {"mos": "1126999", "clip_id": "957500"}}); assert r[0] == 200 and r[1]["ok"], r
    g = s.call("GET", "/api/clips/%d/history" % cid)[1]["story_clips"]
    assert [x["role"] for x in g] == ["original", "hand"] and g[1]["name_id"] == "231126_KARTHIK_V01" and g[1]["blaze_clip_id"] == "957500" and g[1]["mos_object_id"] == "1126999" and g[1]["blaze_story_id"] == "740371"
    row = [x for x in s.call("GET", "/api/clips")[1]["clips"] if x["id"] == cid][0]; assert row["hand_clips"] == 1, "the story card knows, whatever VERSION_SUFFIX is"
    # the poller's full report (with the duration) replaces it; a repeat of the result changes nothing
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "957411", "mos": "1126526", "title": "BASE"}, {"id": "957500", "mos": "1126999", "title": "231126_KARTHIK_V01", "dur_s": 9}]})
    g = s.call("GET", "/api/clips/%d/history" % cid)[1]["story_clips"]; assert len(g) == 2 and g[1]["duration_s"] == 9
    s.svc("POST", "/svc/support/result", {"id": j, "state": "DONE", "result": {"mos": "1126999", "clip_id": "957500"}}); assert len(s.call("GET", "/api/clips/%d/history" % cid)[1]["story_clips"]) == 2

def test_a_failed_or_idless_add_adds_nothing(tmp_path):
    s, cid = story(tmp_path); j = queue_add(s); s.svc("POST", "/svc/support/result", {"id": j, "state": "DONE", "result": {"mos": "1126999"}})      # 'already in the story': no clip id, the poller's report covers it
    j2 = queue_add(s, "5", "OTHER"); s.svc("POST", "/svc/support/result", {"id": j2, "state": "FAILED", "message": "Blaze refused", "result": {"mos": "5", "clip_id": "1"}})
    assert [x["role"] for x in s.call("GET", "/api/clips/%d/history" % cid)[1]["story_clips"]] == ["original"]

def get(s, story_id, clip_id, auth=True):
    rq = urllib.request.Request("http://127.0.0.1:%d/api/blaze-clip/preview?story=%s&clip=%s" % (s.port, story_id, clip_id), headers={"Cookie": (s.cookie or "") if auth else ""})
    try:
        with urllib.request.urlopen(rq, timeout=30) as r: return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e: return e.code, e.headers.get("Content-Type"), e.read()

def test_play_finds_the_file_by_name_and_streams_it_and_leaves_nothing_behind(tmp_path, nitro):
    if not FF: pytest.skip("ffmpeg is not installed")
    d = day_folder(nitro); mxf(d / "231126_KARTHIK_V01.mxf"); s, cid = story(tmp_path)
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "957411", "mos": "1126526", "title": "BASE"}, {"id": "957500", "mos": "1126999", "title": "231126_KARTHIK_V01"}]})
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if "t.db" not in p.name)
    st, ct, body = get(s, "740371", "957500"); assert st == 200 and ct == "video/mp4" and body[4:8] == b"ftyp", (st, ct, body[:80])
    assert before == sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if "t.db" not in p.name), "nothing is written anywhere"

def test_play_explains_every_way_it_can_fail(tmp_path, nitro):
    s, cid = story(tmp_path); day_folder(nitro)
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "957500", "mos": "1126999", "title": "231126_NOT_THERE_V01"}, {"id": "957600", "mos": "7", "title": ""}]})
    st, _, body = get(s, "740371", "957500"); assert st == 404 and b"231126_NOT_THERE_V01" in body and b"Nitro ONAIR" in body, body
    st, _, body = get(s, "740371", "957600"); assert st == 404 and b"no name" in body
    st, _, body = get(s, "740371", "1"); assert st == 404 and b"does not list" in body
    st, _, body = get(s, "999", "957500"); assert st == 404
    assert get(s, "", "")[0] == 400
    assert get(s, "740371", "957500", auth=False)[0] == 401, "login is needed like every other call"

def test_a_name_can_never_lead_outside_the_nitro_folder(tmp_path, nitro):
    secret = tmp_path / "secret.mxf"; secret.write_bytes(b"x" * 50); s, cid = story(tmp_path); day_folder(nitro)
    s.svc("POST", "/svc/story_clips", {"story": "740371", "clips": [{"id": "1", "mos": "1", "title": "../../secret"}, {"id": "2", "mos": "2", "title": "/etc/passwd"}]})
    for c in ("1", "2"): assert get(s, "740371", c)[0] == 404


# ---------- the page ----------
def test_the_page_has_play_on_the_added_clip_and_the_badge_without_version_suffix():
    seg = PAGE[PAGE.index("function gallery("):PAGE.index("function startPreview(")]
    for t in ("/api/blaze-clip/preview?story=", "key=\"h\"+x.blaze_clip_id", "▶ Play preview", "No quality checks"): assert t in seg, t
    assert "No preview or checks" not in PAGE and "c.purl||" in PAGE and PAGE.count("c.purl||") == 2, "startPreview and its error check both use the clip's own address"
    assert "added in Blaze (not made by Storigen)" in PAGE[PAGE.index("function clipBadge("):PAGE.index("function card(")]
    assert 'var APP_VER="10.18.2"' in PAGE


# ---------- v10.18.1: the Groq connection on a Mac whose Python has no certificates ----------
def test_groq_uses_a_ca_bundle_and_names_the_certificate_problem(monkeypatch):
    import ssl
    from autoid_lite import clipsummary as cs
    monkeypatch.delenv("SSL_CERT_FILE", raising=False); monkeypatch.delenv("GROQ_PROXY", raising=False)
    if any(os.path.isfile(f) for f in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt")):
        assert cs._ctx() is not None and any(h.__class__.__name__ == "HTTPSHandler" for h in cs._opener().handlers)
    monkeypatch.setenv("SSL_CERT_FILE", "/x"); assert cs._ctx() is None, "an SSL_CERT_FILE of the machine is respected"
    e = urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"))
    t = cs.why_unreachable(e); assert "Install Certificates.command" in t and "SSL_CERT_FILE" in t
    assert "inspects traffic" in cs.why_unreachable(urllib.error.URLError(ssl.SSLError("handshake failure")))


def test_a_groq_400_or_404_shows_groqs_own_reason_and_never_the_key(monkeypatch):
    import io
    from autoid_lite import clipsummary as cs
    monkeypatch.setenv("GROQ_API_KEY", "gsk_SECRET"); monkeypatch.setenv("GROQ_VISION_MODEL", "some/model")
    def op(code, body):
        def f(req, timeout=0): raise urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(body.encode()))
        return f
    try: cs.post_groq({}, opener=op(404, json.dumps({"error": {"message": "The model `some/model` does not exist or you do not have access to it. gsk_SECRET"}}))); assert False
    except HttpError as e: assert e.status == 502 and "HTTP 404" in e.detail and "does not exist" in e.detail and "gsk_SECRET" not in e.detail and "some/model" in e.detail
    try: cs.post_groq({}, opener=op(400, "not json")); assert False
    except HttpError as e: assert "HTTP 400" in e.detail
