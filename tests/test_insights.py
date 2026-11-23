"""v10.12.0: Name coach, clip quality check, clip frames + Groq description, analytics (Insights tab).
All four are read-only: nothing is written to disk, to Blaze, or (except one event line for who looked) to the database. ffmpeg is needed only for the tests that run it."""
import json, os, pathlib, shutil, sys, urllib.error
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_preview import mxf, clip_on_nitro, FF, subprocess
from test_server import Srv
from autoid_lite.api_bot import plan_names
from autoid_lite.coach import check_name
from autoid_lite.api_insights import summarise
from autoid_lite import quality, clipsummary
from autoid_lite.common import HttpError

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
B = "221126_ELECTION"
def R(v, name, state="ATTACHED"): return {"version": v, "name_id": name, "state": state, "replaced_at": None}
PLAN = plan_names(B, [R(1, B), R(2001, B + "_V01")])          # the story from the desk's question: the base clip and V01
def ck(name, plan=PLAN, **kw): return check_name(plan, B, name, **kw)

# ------------------------------------------------------------------------------------------------ 10. Name coach (pure)
def test_coach_accepts_the_next_right_name_and_says_what_it_does():
    r = ck(B + "_V01_U01"); assert r["ok"] and r["kind"] == "update_added" and "V01" in r["does"]
    r = ck(B + "_V02"); assert r["ok"] and r["kind"] == "append" and any("ADDS" in m for m in r["messages"])
    r = ck(B + "_U01"); assert r["ok"] and r["kind"] == "update" and "main clip" in r["does"]
    assert ck(B + "_U01.mxf")["ok"] and ck(B + "_V02.MXF")["ok"], "the extension is ignored"

def test_coach_refuses_a_skipped_a_used_and_a_missing_number_and_gives_the_exact_fix():
    r = ck(B + "_V01_U02"); assert not r["ok"] and r["kind"] == "skips" and r["fix"] == B + "_V01_U01"
    r = ck(B + "_V03"); assert not r["ok"] and r["kind"] == "skips" and r["fix"] == B + "_V02"
    r = ck(B + "_V01"); assert not r["ok"] and r["kind"] == "used" and r["fix"] == B + "_V02" and any("V01_U01" in m for m in r["messages"]), "tells how to replace V01 instead"
    r = ck(B + "_V02_U01"); assert not r["ok"] and r["kind"] == "no_v" and r["fix"] == B + "_V02"
    r = ck(B + "_U03"); assert not r["ok"] and r["kind"] == "skips" and r["fix"] == B + "_U01"
    r = ck(B); assert not r["ok"] and r["kind"] == "exists" and r["fix"] == B + "_U01", "the plain name is already the main clip"

def test_coach_explains_a_wrong_base_a_wrong_shape_and_a_wrong_number_of_digits():
    r = ck("221226_ELECTION_V02"); assert r["kind"] == "wrong_base" and any("date part" in m for m in r["messages"]) and r["fix"] == B + "_V02"
    r = ck("ELECTION_V02"); assert r["kind"] == "wrong_base" and any("six digits" in m for m in r["messages"])
    r = ck(B + "_V1"); assert not r["ok"] and r["kind"] == "digits" and r["fix"] == B + "_V01"
    for bad in ("_U01_V01", "_U01_U02", "_V01_V02", "_X01", "_V", "_V00"): assert ck(B + bad)["kind"] in ("invalid",), bad
    assert ck("")["kind"] == "empty" and ck("   .mxf")["kind"] == "empty"

def test_coach_tips_and_switch_off_note():
    r = ck(B + "_v02"); assert r["ok"] and any("capitals" in m for m in r["messages"])
    r = ck(B + "_V02", suffix_on=False); assert r["ok"] and any("VERSION_SUFFIX" in m for m in r["messages"])
    r = ck(B + " _V02"); assert r["ok"] and any("spaces" in m for m in r["messages"])

def test_coach_with_nothing_registered_and_with_full_chains():
    empty = plan_names(B, []); r = check_name(empty, B, B); assert r["ok"] and r["kind"] == "main"
    r = check_name(empty, B, B + "_U01"); assert not r["ok"] and r["kind"] == "no_main" and r["fix"] == B
    full = plan_names(B, [R(1, B), R(1099, B + "_U99"), R(2099, B + "_V99")])
    assert check_name(full, B, B + "_U01")["kind"] == "full" and check_name(full, B, B + "_V01")["kind"] == "full"

# ------------------------------------------------------------------------------------------------ 5. Quality check (pure parts)
LOG = """[blackdetect @ 0x1] black_start:0 black_end:2 black_duration:2
[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 0
[freezedetect @ 0x2] lavfi.freezedetect.freeze_duration: 2
[silencedetect @ 0x3] silence_start: 3.5
[silencedetect @ 0x3] silence_end: 9 | silence_duration: 5.5
[Parsed_ebur128_1 @ 0x4] Summary:
  Integrated loudness:
    I:         -23.4 LUFS
    Threshold: -33.4 LUFS
  Loudness range:
    LRA:         0.0 LU
  True peak:
    Peak:       -0.2 dBFS
"""
INFO = {"duration_s": 10.0, "has_video": True, "width": 1920, "height": 1080, "dar": "16:9", "fps": 25.0, "video_codec": "mpeg2video", "audio_tracks": 1}
def lvl(res, name): return next(c["level"] for c in res["checks"] if c["name"] == name)

def test_the_ffmpeg_log_is_read_correctly():
    p = quality.parse_log(LOG, 10.0)
    assert p["black"] == [(0.0, 2.0)] and p["freeze"] == [(0.0, 2.0)] and p["silence"] == [(3.5, 5.5)] and p["lufs"] == -23.4 and p["peak"] == -0.2
    p = quality.parse_log("[silencedetect @ 0x3] silence_start: 6\n[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 4", 10.0)
    assert p["silence"] == [(6.0, 4.0)] and p["freeze"] == [(4.0, 6.0)], "a segment still open at the end runs to the end"
    assert quality.parse_log("", 10.0) == {"black": [], "freeze": [], "silence": [], "lufs": None, "peak": None}

def test_the_verdict_is_the_worst_finding_in_plain_words():
    r = quality.judge(INFO, quality.parse_log(LOG, 10.0), attached_s=10)
    assert r["verdict"] == "warn" and lvl(r, "Black") == "warn" and lvl(r, "Silence") == "warn" and lvl(r, "Peaks") == "warn" and lvl(r, "Frozen") == "ok" and lvl(r, "Length") == "ok" and lvl(r, "Sound") == "ok"
    clean = quality.judge(INFO, {"black": [], "freeze": [], "silence": [], "lufs": -23.0, "peak": -3.0}, attached_s=10); assert clean["verdict"] == "ok" and all(c["level"] == "ok" for c in clean["checks"])
    silent = quality.judge(INFO, {"black": [], "freeze": [], "silence": [(0, 10)], "lufs": -70.0, "peak": None}); assert silent["verdict"] == "fail" and lvl(silent, "Sound") == "fail"
    black = quality.judge(INFO, {"black": [(0.0, 10.0)], "freeze": [], "silence": [], "lufs": -23.0, "peak": -3.0}); assert black["verdict"] == "fail" and lvl(black, "Black") == "fail"
    frozen = quality.judge(INFO, {"black": [], "freeze": [(0.0, 10.0)], "silence": [], "lufs": -23.0, "peak": -3.0}); assert frozen["verdict"] == "fail" and lvl(frozen, "Frozen") == "fail"
    mid = quality.judge(INFO, {"black": [(4.0, 3.0)], "freeze": [], "silence": [], "lufs": -23.0, "peak": -3.0}); assert lvl(mid, "Black") == "warn" and "middle" in [c for c in mid["checks"] if c["name"] == "Black"][0]["text"]
    assert lvl(quality.judge(INFO, {"black": [], "freeze": [], "silence": [], "lufs": -10.0, "peak": -3.0}), "Sound") == "warn"
    assert lvl(quality.judge(INFO, {"black": [], "freeze": [], "silence": [], "lufs": -40.0, "peak": -3.0}), "Sound") == "warn"
    assert lvl(quality.judge(dict(INFO, dar="4:3", width=720, height=540), {"black": [], "freeze": [], "silence": [], "lufs": -23.0, "peak": -3.0}), "Shape") == "warn"
    assert lvl(quality.judge(INFO, {"black": [], "freeze": [], "silence": [], "lufs": -23.0, "peak": -3.0}, attached_s=4), "Length") == "warn", "the file is 10 s, the story has 4 s attached"
    noaudio = quality.judge(dict(INFO, audio_tracks=0), {"black": [], "freeze": [], "silence": [], "lufs": None, "peak": None}); assert noaudio["verdict"] == "fail" and lvl(noaudio, "Sound") == "fail"
    to = quality.judge(INFO, {"black": [], "freeze": [], "silence": [], "lufs": -23.0, "peak": -3.0}, timed_out=True); assert lvl(to, "Analysis") == "warn"

# ------------------------------------------------------------------------------------------------ 5. Quality check (real ffmpeg + the endpoint)
need_ff = pytest.mark.skipif(not (FF and shutil.which("ffprobe")), reason="ffmpeg / ffprobe is not installed")
def black_silent(path, secs=3):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=%d" % secs, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(secs),
                    "-c:v", "mpeg2video", "-c:a", "pcm_s16le", "-ar", "48000", "-f", "mxf", str(path)], check=True)
def tree(p): return sorted(str(x.relative_to(p)) for x in p.rglob("*") if x.suffix not in (".db", "") or x.is_file() and "t.db" not in x.name)
def nitro(tmp_path, monkeypatch):
    d = tmp_path / "ONAIR" / "Nov-26" / "22-11-2026"; d.mkdir(parents=True); monkeypatch.setenv("NITRO_DIR", str(tmp_path / "ONAIR")); return d

@need_ff
def test_a_good_clip_has_no_failure_and_a_black_silent_clip_fails(tmp_path, monkeypatch):
    d = nitro(tmp_path, monkeypatch); good, bad = d / "221126_GOOD.mxf", d / "221126_BAD.mxf"; mxf(good, 3); black_silent(bad)
    r = quality.analyse(str(good), attached_s=3); assert r["verdict"] in ("ok", "warn") and not [c for c in r["checks"] if c["level"] == "fail"] and r["facts"]["width"] == 640 and r["facts"]["audio_tracks"] == 1
    r = quality.analyse(str(bad)); assert r["verdict"] == "fail" and lvl(r, "Black") == "fail" and lvl(r, "Sound") == "fail"

@need_ff
def test_the_quality_endpoint_reads_logs_who_looked_and_writes_nothing(tmp_path, monkeypatch):
    d = nitro(tmp_path, monkeypatch); f = d / "221126_BAD.mxf"; black_silent(f)
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; c = clip_on_nitro(s, f); before = tree(tmp_path)
    st, r = s.call("GET", "/api/clips/%d/quality" % c["id"]); assert st == 200 and r["verdict"] == "fail" and r["checks"]
    assert tree(tmp_path) == before, "no file, no cache, nothing in the project"
    with s.app.db.tx() as cur: ev = cur.q("SELECT actor, action, details FROM events WHERE action='quality_check'")
    assert len(ev) == 1 and "fail" in ev[0]["details"] and "jpeg" not in ev[0]["details"].lower()
    s.cookie = None; assert s.call("GET", "/api/clips/%d/quality" % c["id"])[0] == 401

def test_the_quality_endpoint_guards(tmp_path, monkeypatch):
    (tmp_path / "ONAIR").mkdir(); other = tmp_path / "secret.mxf"; other.write_bytes(b"x" * 100); monkeypatch.setenv("NITRO_DIR", str(tmp_path / "ONAIR"))
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    c = clip_on_nitro(s, other); st, r = s.call("GET", "/api/clips/%d/quality" % c["id"]); assert st in (403, 503), "outside Nitro is never read (503 only when ffmpeg is missing)"
    assert shutil.which("ffmpeg") is None or st == 403
    c2 = s.call("POST", "/api/manual", {"rundown": "14:00 Bulletin", "story": "Not there"})[1]; assert s.call("GET", "/api/clips/%d/quality" % c2["id"])[0] == 404
    assert s.call("GET", "/api/clips/99999/quality")[0] == 404
    monkeypatch.setenv("QUALITY_ENABLED", "0"); assert s.call("GET", "/api/clips/%d/quality" % c["id"])[0] == 404

@need_ff
def test_only_one_check_runs_at_a_time(tmp_path, monkeypatch):
    d = nitro(tmp_path, monkeypatch); f = d / "221126_X.mxf"; mxf(f, 2)
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; c = clip_on_nitro(s, f)
    sem = quality._slot(); assert sem.acquire(blocking=False)
    try: assert s.call("GET", "/api/clips/%d/quality" % c["id"])[0] == 429
    finally: sem.release()
    assert s.call("GET", "/api/clips/%d/quality" % c["id"])[0] == 200

# ------------------------------------------------------------------------------------------------ 1. Frames + Groq
class Resp:
    def __init__(self, body): self.b = body if isinstance(body, bytes) else json.dumps(body).encode()
    def read(self): return self.b
    def __enter__(self): return self
    def __exit__(self, *a): return False
def groq_ok(text="Smoke rises over a beach and firefighters stand by.\nTags: fire, beach, smoke"):
    seen = {}
    def opener(req, timeout=None):
        seen.update(url=req.full_url, auth=req.get_header("Authorization"), body=json.loads(req.data), timeout=timeout); return Resp({"choices": [{"message": {"content": text}}]})
    return opener, seen
def http_err(code): return urllib.error.HTTPError("https://api.groq.com", code, "x", {}, None)
KEY = "gsk_TESTSECRET_0123456789"
def with_key(monkeypatch, **kw):
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    for k, v in kw.items(): monkeypatch.setenv(k, v)
    clipsummary._hits.clear()

def test_frame_times_are_spread_evenly_and_the_answer_is_parsed():
    assert clipsummary.times(20, 4) == [2.5, 7.5, 12.5, 17.5] and clipsummary.times(0, 4) == [0.0] and clipsummary.times(None, 3) == [0.0]
    a = clipsummary.parse_answer("Summary: A man speaks at a podium.\nTags: Politics, Speech, #podium."); assert a == {"summary": "A man speaks at a podium.", "tags": ["politics", "speech", "podium"]}
    assert clipsummary.parse_answer("Just a sentence with no tags line.") == {"summary": "Just a sentence with no tags line.", "tags": []}

def test_groq_request_has_the_key_the_pictures_and_the_model_and_no_more(monkeypatch):
    with_key(monkeypatch); op, seen = groq_ok(); out = clipsummary.ask_groq([b"\xff\xd8a", b"\xff\xd8b", b"\xff\xd8c"], opener=op)
    assert out["summary"].startswith("Smoke rises") and out["tags"] == ["fire", "beach", "smoke"] and out["model"] == clipsummary.DEFAULT_MODEL
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions" and seen["auth"] == "Bearer " + KEY and seen["body"]["model"] == clipsummary.DEFAULT_MODEL
    parts = seen["body"]["messages"][0]["content"]; assert parts[0]["type"] == "text" and "3 pictures" in parts[0]["text"] and "do not name any person" in parts[0]["text"]
    assert [p["type"] for p in parts[1:]] == ["image_url"] * 3 and all(p["image_url"]["url"].startswith("data:image/jpeg;base64,") for p in parts[1:])
    monkeypatch.setenv("GROQ_VISION_MODEL", "some/other-model"); op2, seen2 = groq_ok(); clipsummary.ask_groq([b"\xff\xd8a"], opener=op2); assert seen2["body"]["model"] == "some/other-model"

def test_groq_problems_become_clear_messages_and_never_show_the_key(monkeypatch):
    with_key(monkeypatch)
    def boom(e): 
        def op(req, timeout=None): raise e
        return op
    for code, word, status in ((401, "key", 502), (403, "key", 502), (429, "too many", 429), (404, "GROQ_VISION_MODEL", 502), (400, "GROQ_VISION_MODEL", 502), (500, "error", 502)):
        with pytest.raises(HttpError) as ei: clipsummary.ask_groq([b"\xff\xd8a"], opener=boom(http_err(code)))
        assert ei.value.status == status and word in ei.value.detail and KEY not in ei.value.detail, code
    with pytest.raises(HttpError) as ei: clipsummary.ask_groq([b"\xff\xd8a"], opener=boom(urllib.error.URLError("no route")))
    assert ei.value.status == 502 and "could not be reached" in ei.value.detail and KEY not in ei.value.detail
    with pytest.raises(HttpError) as ei: clipsummary.ask_groq([b"\xff\xd8a"], opener=lambda req, timeout=None: Resp(b"not json")); assert ei.value.status == 502
    with pytest.raises(HttpError) as ei: clipsummary.ask_groq([b"\xff\xd8a"], opener=lambda req, timeout=None: Resp({"choices": []})); assert ei.value.status == 502

def test_no_key_means_no_ai_and_the_hourly_ceiling_holds(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False); assert not clipsummary.ai_available()
    with pytest.raises(HttpError) as ei: clipsummary.ask_groq([b"\xff\xd8a"], opener=groq_ok()[0]); assert ei.value.status == 503
    with_key(monkeypatch, GROQ_MAX_PER_HOUR="2"); op = groq_ok()[0]; clipsummary.ask_groq([b"\xff\xd8a"], opener=op); clipsummary.ask_groq([b"\xff\xd8a"], opener=op)
    with pytest.raises(HttpError) as ei: clipsummary.ask_groq([b"\xff\xd8a"], opener=op); assert ei.value.status == 429
    monkeypatch.setenv("CLIP_SUMMARY", "0"); assert not clipsummary.ai_available()

@need_ff
def test_real_frames_are_small_jpegs_in_memory_and_nothing_is_written(tmp_path, monkeypatch):
    import base64
    d = nitro(tmp_path, monkeypatch); f = d / "221126_FIRE.mxf"; mxf(f, 4); before = tree(tmp_path); with_key(monkeypatch); op, seen = groq_ok()
    out = clipsummary.describe(str(f), ai=False); assert len(out["frames"]) == 4 and "summary" not in out and all(base64.b64decode(x["jpeg_b64"])[:2] == b"\xff\xd8" for x in out["frames"])
    assert [x["t"] for x in out["frames"]] == [0.5, 1.5, 2.5, 3.5]
    out = clipsummary.describe(str(f), ai=True, opener=op); assert out["summary"] and out["tags"] and len(seen["body"]["messages"][0]["content"]) == 5
    out = clipsummary.describe(str(f), ai=True, opener=lambda r, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("down")))
    assert len(out["frames"]) == 4 and "summary" not in out and "could not be reached" in out["ai_error"], "the pictures still come when Groq is down"
    assert tree(tmp_path) == before

@need_ff
def test_the_frames_endpoint_without_and_with_ai(tmp_path, monkeypatch):
    d = nitro(tmp_path, monkeypatch); f = d / "221126_FIRE.mxf"; mxf(f, 3); monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200; c = clip_on_nitro(s, f)
    st, r = s.call("GET", "/api/clips/%d/frames?ai=0" % c["id"]); assert st == 200 and len(r["frames"]) == 4 and "summary" not in r
    assert s.call("GET", "/api/clips/%d/frames?ai=1" % c["id"])[0] == 503, "no key: no AI, and it says so"
    with_key(monkeypatch); monkeypatch.setattr(clipsummary, "ask_groq", lambda j, **k: {"summary": "Smoke over a beach.", "tags": ["fire"], "model": "m"})
    st, r = s.call("GET", "/api/clips/%d/frames?ai=1" % c["id"]); assert st == 200 and r["summary"] == "Smoke over a beach." and KEY not in json.dumps(r)
    with s.app.db.tx() as cur: ev = cur.q("SELECT details FROM events WHERE action='clip_ai_summary'")
    assert len(ev) == 1 and KEY not in ev[0]["details"] and "jpeg" not in ev[0]["details"].lower()
    s.cookie = None; assert s.call("GET", "/api/clips/%d/frames?ai=0" % c["id"])[0] == 401

def test_the_key_never_reaches_the_browser_or_the_page(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False); s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    cfg = s.call("GET", "/api/config")[1]; assert cfg["ai_summary"] is False and cfg["quality"] is True and cfg["frames"] is True
    with_key(monkeypatch); cfg = s.call("GET", "/api/config")[1]; assert cfg["ai_summary"] is True and KEY not in json.dumps(cfg)
    assert "gsk_" not in PAGE and "api.groq.com" not in PAGE, "the page names the setting, never a key or the service address"
    monkeypatch.setenv("CLIP_SUMMARY", "0"); assert s.call("GET", "/api/config")[1]["ai_summary"] is False

# ------------------------------------------------------------------------------------------------ 8. Analytics
def row(day="2026-11-22", v=1, state="ATTACHED", c="2026-11-22T10:00:00Z", n="2026-11-22T10:20:00Z", a="2026-11-22T10:25:00Z", show="Noon", start="2026-11-22T10:10:00+00:00", name="X"):
    return {"day": day, "version": v, "state": state, "created_at": c, "on_nitro_at": n, "attached_at": a, "show": show, "start_at": start, "name_id": name}

def test_analytics_numbers_from_the_registrys_own_times():
    rows = [row(), row(a="2026-11-22T10:05:00Z", n="2026-11-22T10:02:00Z", start="2026-11-22T11:00:00+00:00", show="Evening", name="Y"), row(v=1001, name="Z"), row(v=2001, state="WAITING_FOR_CLIP", n=None, a=None), row(v=10101, state="NEEDS_DESK", a=None),
            row(day="2026-11-21", c="2026-11-21T09:00:00Z", n="2026-11-21T09:30:00Z", a="2026-11-21T10:00:00Z", start="2026-11-21T09:45:00+00:00", show="Noon")]
    o = summarise(rows); T = o["total"]
    assert T["clips"] == 6 and T["attached"] == 4 and T["waiting"] == 1 and T["problem"] == 1 and T["updates"] == 2 and T["added"] == 1, "U and V-U count as updates, V as added"
    assert T["late"] == 3 and T["to_attach"]["n"] == 4 and T["to_attach"]["median"] == 25.0 and T["to_nitro"]["median"] in (20.0, 30.0) and T["nitro_to_attach"]["median"] == 5.0
    sh = {x["show"]: x for x in o["shows"]}; assert sh["Evening"]["late"] == 0 and sh["Noon"]["clips"] == 5 and [d["day"] for d in o["days"]] == ["2026-11-21", "2026-11-22"]
    assert o["slowest"][0]["minutes"] == 60.0 and summarise([])["total"]["clips"] == 0
    assert summarise([row(c="garbage", n="bad", a="worse", start=None)])["total"]["to_attach"]["median"] is None, "bad times do not stop the page"

def test_analytics_endpoint_reads_the_registry_and_writes_nothing(tmp_path):
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    a = s.call("POST", "/api/manual", {"rundown": "12:00 Noon", "story": "Fire"})[1]; b = s.call("POST", "/api/manual", {"rundown": "12:00 Noon", "story": "Flood"})[1]
    with s.app.db.tx() as cur:
        cur.x("UPDATE rundowns SET start_at='2026-11-22T10:10:00+00:00'")
        cur.x("UPDATE clip_ids SET state='ATTACHED', created_at='2026-11-22T10:00:00Z', on_nitro_at='2026-11-22T10:20:00Z', attached_at='2026-11-22T10:25:00Z' WHERE id=?", (a["id"],))
        n0 = cur.one("SELECT COUNT(*) AS n FROM events")["n"]
    st, r = s.call("GET", "/api/analytics?days=1"); assert st == 200 and r["total"]["clips"] == 2 and r["total"]["attached"] == 1 and r["total"]["late"] == 1 and r["total"]["to_attach"]["median"] == 25.0 and r["days_asked"] == 1
    assert r["shows"][0]["show"] == "12:00 Noon"
    assert s.call("GET", "/api/analytics?days=0")[1]["days_asked"] == 1 and s.call("GET", "/api/analytics?days=999")[1]["days_asked"] == 31 and s.call("GET", "/api/analytics?days=abc")[0] == 400
    with s.app.db.tx() as cur: assert cur.one("SELECT COUNT(*) AS n FROM events")["n"] == n0
    s.cookie = None; assert s.call("GET", "/api/analytics")[0] == 401

# ------------------------------------------------------------------------------------------------ name check through the assistant's call
def test_the_name_check_call_uses_the_real_story(tmp_path, monkeypatch):
    from test_blaze_poll import Fake, Srv as _S
    from test_quick_test_button import dry
    from test_blaze_poll import ready_clip
    from test_support_menu import run
    monkeypatch.setenv("VERSION_SUFFIX", "on"); monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("CHECK_CHAR", "1")
    s, f, p, e = dry(tmp_path); ready_clip(s, f, p); run(p)
    base = s.call("GET", "/api/bot/story?rundown=34427&story=724921")[1]["base"]; q = "/api/bot/checkname?rundown=34427&story=724921&name="
    st, r = s.call("GET", q + base + "_V01"); assert st == 200 and r["ok"] and r["kind"] == "append" and r["base"] == base
    st, r = s.call("GET", q + base + "_V05"); assert st == 200 and not r["ok"] and r["fix"] == base + "_V01"
    st, r = s.call("GET", q + base + "_U01.mxf"); assert r["ok"] and r["kind"] == "update"
    assert s.call("GET", "/api/bot/checkname?rundown=34427&story=1&name=x")[0] == 404 and s.call("GET", "/api/bot/checkname?rundown=34427&name=x")[0] == 400
    assert s.call("GET", q + "A" * 300)[0] == 400
    with s.app.db.tx() as cur: n0 = (cur.one("SELECT COUNT(*) AS n FROM events")["n"], cur.one("SELECT COUNT(*) AS n FROM clip_ids")["n"])
    s.call("GET", q + base + "_V01")
    with s.app.db.tx() as cur: assert n0 == (cur.one("SELECT COUNT(*) AS n FROM events")["n"], cur.one("SELECT COUNT(*) AS n FROM clip_ids")["n"]), "the coach only reads"

# ------------------------------------------------------------------------------------------------ the page
def test_the_page_has_the_tab_the_buttons_and_the_name_check():
    for t in ('data-tab="insights"', 'id="insbox"', '"insights"].includes', 'toggleCls($("#insbox")', 'if(pgTab==="insights")insLoad()', "/api/analytics?days=", "Slowest to attach"): assert t in PAGE, t
    for t in ("function insBtns(", "function insPanel(", "🔍 Check quality", "🖼 Frames", "✨ Describe with AI", "/quality", "/frames?ai=0", "/frames?ai=1", "outside AI service", "pl.append(insBtns(x.id,x.on_nitro,x,{name:x.file,duration_s:x.duration_s}))", "sec.append(b,dl,insBtns(c.id,on,c,h.file))"): assert t in PAGE, t
    assert "pv.id,!!pv.node,cfg.preview,insVer," in PAGE, "the detail redraws when a result arrives"
    for t in ("function botCheckName(", "/api/bot/checkname?rundown=", "Check a file name", "Use this name instead:"): assert t in PAGE, t
    seg = PAGE[PAGE.index("/* ===== v10.12.0: Insights"):PAGE.index("/* ===== v10.11.0: Clip assistant")]; assert "innerHTML" not in seg and 'method:"POST"' not in seg and "post(" not in seg, "the new code only reads and builds the page with text nodes"
    bot = PAGE[PAGE.index("/* ===== v10.11.0: Clip assistant"):]; assert "innerHTML" not in bot and "/api/support/" not in bot and 'method:"POST"' not in bot and "post(" not in bot, "the assistant is still read-only"

def test_the_new_settings_are_documented_in_the_env_example():
    t = (ROOT / "autoid.env.example").read_text(encoding="utf-8")
    for k in ("GROQ_API_KEY=", "GROQ_VISION_MODEL=", "CLIP_SUMMARY=", "GROQ_MAX_PER_HOUR=", "CLIP_FRAMES=", "QUALITY_ENABLED=", "QUALITY_MAX_SECONDS=", "QUALITY_MAX_JOBS="): assert k in t, k
    assert "gsk_" not in t, "no real key in the example"
