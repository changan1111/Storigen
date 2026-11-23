"""v10.12.0 Clip quality check. On demand only (a button on the clip): ffprobe reads the file facts, then ONE ffmpeg pass looks for black frames, a frozen picture, silence and the loudness.
Nothing is written anywhere: the analysis goes to ffmpeg's null output, the answer is a small JSON that is shown and forgotten. It runs at low priority, one at a time (QUALITY_MAX_JOBS),
with a wall-clock limit (QUALITY_MAX_SECONDS), so it can never slow the poller or the watcher. judge() and parse_log() are pure functions and are tested without ffmpeg."""
from __future__ import annotations
import json, os, re, subprocess, sys, threading
from .common import HttpError
from . import preview

_lock = threading.Lock(); _slots = {"n": 0, "sem": None}


def enabled(): return os.getenv("QUALITY_ENABLED", "1") != "0"
def ffprobe():
    p = os.getenv("QUALITY_FFPROBE")
    if p: return p
    f = preview.ffmpeg()
    if f:
        cand = os.path.join(os.path.dirname(f), "ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        if os.access(cand, os.X_OK): return cand
    import shutil; return shutil.which("ffprobe")
def _slot():
    n = max(1, int(os.getenv("QUALITY_MAX_JOBS", "1") or 1))
    with _lock:
        if _slots["n"] != n: _slots["n"], _slots["sem"] = n, threading.BoundedSemaphore(n)
        return _slots["sem"]
def _low_priority(): return {"creationflags": 0x4000} if sys.platform == "win32" else {"preexec_fn": lambda: os.nice(10)}
def _num(s, d=None):
    try: return float(s)
    except (TypeError, ValueError): return d


def probe(path, timeout=30):
    """File facts from ffprobe: duration, picture size and shape, frame rate, number of audio tracks, codecs."""
    cmd = [ffprobe(), "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,display_aspect_ratio,sample_aspect_ratio,r_frame_rate,channels:format=duration", "-of", "json", path]
    try: out = subprocess.run(cmd, capture_output=True, timeout=timeout, **_low_priority()).stdout
    except (OSError, subprocess.SubprocessError): return {}
    try: j = json.loads(out or b"{}")
    except ValueError: return {}
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
    a = [s for s in j.get("streams", []) if s.get("codec_type") == "audio"]
    fr = (v or {}).get("r_frame_rate", "0/0"); n, _, d = fr.partition("/"); fps = round(_num(n, 0) / (_num(d, 1) or 1), 2) if v else None
    return {"duration_s": _num((j.get("format") or {}).get("duration")), "width": (v or {}).get("width"), "height": (v or {}).get("height"), "dar": (v or {}).get("display_aspect_ratio"),
            "fps": fps, "video_codec": (v or {}).get("codec_name"), "audio_tracks": len(a), "audio_codec": a[0].get("codec_name") if a else None, "has_video": v is not None}


def parse_log(text, duration=None):
    """The text ffmpeg printed (stderr) -> {black: [(start, dur)], freeze: [(start, dur)], silence: [(start, dur)], lufs, peak}. A segment still open when the file ends runs to the end."""
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+)\s+black_end:[\d.]+\s+black_duration:([\d.]+)", text)]
    fs = [float(x) for x in re.findall(r"freeze_start:\s*([\d.]+)", text)]; fd = [float(x) for x in re.findall(r"freeze_duration:\s*([\d.]+)", text)]
    freeze = [(s, fd[i] if i < len(fd) else max(0.0, (duration or s) - s)) for i, s in enumerate(fs)]
    ss = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", text)]; sd = [float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", text)]
    silence = [(max(0.0, s), sd[i] if i < len(sd) else max(0.0, (duration or s) - s)) for i, s in enumerate(ss)]
    li = re.findall(r"\bI:\s+(-?[\d.]+|-inf)\s+LUFS", text); pk = re.findall(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS", text)
    return {"black": black, "freeze": freeze, "silence": silence, "lufs": _num(li[-1]) if li else None, "peak": _num(pk[-1]) if pk else None}


def limits():
    g = lambda k, d: _num(os.getenv(k), d)
    return {"black_s": g("QUALITY_BLACK_SECS", 2.0), "black_edge_s": g("QUALITY_BLACK_EDGE_SECS", 1.0), "freeze_s": g("QUALITY_FREEZE_SECS", 3.0), "silence_s": g("QUALITY_SILENCE_SECS", 3.0),
            "lufs_min": g("QUALITY_LUFS_MIN", -30.0), "lufs_max": g("QUALITY_LUFS_MAX", -16.0), "peak_max": g("QUALITY_PEAK_MAX", -1.0), "len_diff_s": g("QUALITY_LENGTH_DIFF_SECS", 3.0)}


def judge(info, rep, attached_s=None, lim=None, timed_out=False):
    """Facts + findings -> verdict. checks: [{name, level ok|warn|fail, text}]; verdict = the worst level. Plain words, nothing technical the desk cannot act on."""
    L = lim or limits(); chk = []
    def add(name, level, text): chk.append({"name": name, "level": level, "text": text})
    dur = info.get("duration_s")
    if not info.get("has_video"): add("Picture", "fail", "No picture track found in the file.")
    else:
        add("Picture", "ok", "%sx%s%s%s" % (info.get("width"), info.get("height"), " · " + str(info["fps"]) + " fps" if info.get("fps") else "", " · " + info["video_codec"] if info.get("video_codec") else ""))
        dar = info.get("dar")
        try: a, b = (dar or "").split(":"); shape = float(a) / float(b)
        except (ValueError, ZeroDivisionError): shape = (info["width"] / info["height"]) if info.get("width") and info.get("height") else None
        if shape and abs(shape - 16 / 9) > 0.03: add("Shape", "warn", "The picture is not 16:9 (it is %s). It may show with bars or stretched on air." % (dar or "%.2f:1" % shape))
        else: add("Shape", "ok", "16:9")
    if not info.get("audio_tracks"): add("Sound", "fail", "No sound track found in the file.")
    elif rep.get("lufs") is None and not timed_out: add("Sound", "warn", "The loudness could not be measured.")
    elif rep.get("lufs") is not None:
        lu = rep["lufs"]
        if lu <= -60: add("Sound", "fail", "The clip is silent.")
        elif lu < L["lufs_min"]: add("Sound", "warn", "Too quiet: %.1f LUFS (a news clip is usually about -23)." % lu)
        elif lu > L["lufs_max"]: add("Sound", "warn", "Too loud: %.1f LUFS (a news clip is usually about -23)." % lu)
        else: add("Sound", "ok", "Loudness %.1f LUFS" % lu)
        if rep.get("peak") is not None and rep["peak"] > L["peak_max"]: add("Peaks", "warn", "The sound peaks at %.1f dBFS: it may distort." % rep["peak"])
    bl = rep.get("black") or []; edge, mid = [], []
    for s, d in bl:
        (edge if s < 0.5 or (dur and s + d >= dur - 0.5) else mid).append((s, d))
    if dur and sum(d for _, d in bl) >= dur - 0.5 and bl: add("Black", "fail", "The whole clip is black.")
    elif any(d >= L["black_s"] for _, d in mid): add("Black", "warn", "Black picture in the middle: " + ", ".join("%.0f s at %s" % (d, _tc(s)) for s, d in mid if d >= L["black_s"]) + ".")
    elif any(d >= L["black_edge_s"] for _, d in edge): add("Black", "warn", "Black at the start or end: " + ", ".join("%.1f s at %s" % (d, _tc(s)) for s, d in edge if d >= L["black_edge_s"]) + ".")
    elif info.get("has_video"): add("Black", "ok", "No black picture")
    fr = [(s, d) for s, d in (rep.get("freeze") or []) if d >= L["freeze_s"]]
    if info.get("has_video"):
        if dur and fr and sum(d for _, d in fr) >= dur - 0.5: add("Frozen", "fail", "The picture never moves (frozen for the whole clip).")
        elif fr: add("Frozen", "warn", "The picture is frozen: " + ", ".join("%.0f s at %s" % (d, _tc(s)) for s, d in fr) + ".")
        else: add("Frozen", "ok", "No frozen picture")
    sl = [(s, d) for s, d in (rep.get("silence") or []) if d >= L["silence_s"]]
    if info.get("audio_tracks") and not any(c["name"] == "Sound" and c["level"] == "fail" for c in chk):
        if sl: add("Silence", "warn", "Silent for " + ", ".join("%.0f s at %s" % (d, _tc(s)) for s, d in sl) + ".")
        else: add("Silence", "ok", "No long silence")
    if dur is not None and attached_s is not None:
        if abs(dur - attached_s) > L["len_diff_s"]: add("Length", "warn", "The file is %.0f s but the story has %d s attached. Check that the right clip is attached." % (dur, attached_s))
        else: add("Length", "ok", "File %.0f s · attached %d s" % (dur, attached_s))
    elif dur is not None: add("Length", "ok", "File %.0f s" % dur)
    if timed_out: add("Analysis", "warn", "The check stopped at the time limit: only the first part of the clip was checked.")
    level = "fail" if any(c["level"] == "fail" for c in chk) else "warn" if any(c["level"] == "warn" for c in chk) else "ok"
    return {"verdict": level, "checks": chk, "facts": info}


def _tc(s): s = int(s); return "%d:%02d" % (s // 60, s % 60)


def _job_slot():
    sem = _slot()
    if not sem.acquire(blocking=False): raise HttpError(429, "Another clip check is running. Try again in a moment")
    return sem


def analyse(path, attached_s=None):
    """Run the whole check on a file inside NITRO_DIR (same path guard as the preview). Blocks until done; raises HttpError for the user-facing problems."""
    if not enabled(): raise HttpError(404, "The quality check is switched off (QUALITY_ENABLED=0)")
    ff, fp = preview.ffmpeg(), ffprobe()
    if not ff or not fp: raise HttpError(503, "ffmpeg / ffprobe is not installed on the Storigen machine")
    real = preview.check_path(path); sem = _job_slot()
    try:
        info = probe(real)
        if not info: raise HttpError(422, "ffprobe could not read this file (it may still be copying, or the format is not supported)")
        cap = int(float(os.getenv("QUALITY_MAX_SECONDS", "180") or 180)); h = int(os.getenv("QUALITY_HEIGHT", "288") or 288)
        cmd = [ff, "-nostdin", "-nostats", "-hide_banner", "-v", "info", "-threads", os.getenv("QUALITY_THREADS", "2"), "-i", real, "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
        if info.get("has_video"): cmd += ["-vf", "scale=-2:%d,blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-60dB:d=2" % h]
        if info.get("audio_tracks"): cmd += ["-af", "silencedetect=n=-50dB:d=2,ebur128=peak=true:framelog=quiet"]
        cmd += ["-f", "null", "-"]
        timed = False
        try: p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=cap, **_low_priority()); log = p.stderr.decode("utf-8", "replace")
        except subprocess.TimeoutExpired as e: timed = True; log = (e.stderr or b"").decode("utf-8", "replace")
        except OSError: raise HttpError(503, "ffmpeg could not be started")
        return judge(info, parse_log(log, info.get("duration_s")), attached_s, timed_out=timed)
    finally: sem.release()
