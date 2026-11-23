"""v10.1.0: play a clip from the Nitro ONAIR folder in the dashboard. Nothing is stored: every Play converts the MXF to a small H.264 stream with ffmpeg
and sends it straight to the browser (no cache, no temp file, nothing written in the project). It only runs when someone clicks Play, at low CPU
priority, one at a time by default (PREVIEW_MAX_JOBS), and it stops the moment the browser stops watching."""
import datetime as dt, os, re, shutil, subprocess, sys, threading
from .common import HttpError
from .ids import norm_name

_slots = {"n": 0, "sem": None}; _lock = threading.Lock()

def enabled(): return os.getenv("PREVIEW_ENABLED", "1") != "0"
def ffmpeg():
    p = os.getenv("PREVIEW_FFMPEG") or shutil.which("ffmpeg")
    if p: return p
    for c in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/local/bin/ffmpeg"):      # v10.3.1: a Mac login service has no Homebrew folder in its PATH, so also look where Homebrew / MacPorts put it
        if os.access(c, os.X_OK): return c
    return None
def _slot():
    n = max(1, int(os.getenv("PREVIEW_MAX_JOBS", "1") or 1))
    with _lock:
        if _slots["n"] != n: _slots["n"], _slots["sem"] = n, threading.BoundedSemaphore(n)
        return _slots["sem"]

def check_path(p):
    """The file must be inside NITRO_DIR (after resolving links) and exist: nothing else can ever be streamed."""
    root = os.getenv("NITRO_DIR", "")
    if not root: raise HttpError(503, "NITRO_DIR is not set for the web service, so Storigen does not know where the Nitro files are")
    root, real = os.path.realpath(root), os.path.realpath(p)
    if not (real == root or real.startswith(root + os.sep)): raise HttpError(403, "This file is outside the Nitro folder")
    if not os.path.isfile(real): raise HttpError(404, "The file is not reachable now (Nitro folder not mounted, or the file was moved)")
    return real

def find_nitro_file(title):
    """v10.18.0: look for the Nitro file of a clip that Storigen did not make (added with + / Add media, or by hand), by its NAME. -> (path or None, text saying where it looked).
    Looked up fresh on every Play, remembered nowhere. It uses the settings the watcher uses: NITRO_DIR, NITRO_DATE_PATH (the day folders: today, and NITRO_SCAN_DAYS_BACK / _AHEAD around it),
    NITRO_EXTS and NITRO_SCAN_DEPTH. Spaces, dashes, underscores and capitals do not matter in the name (the same rule the whole tool uses). The newest file wins if there are several."""
    root = os.getenv("NITRO_DIR", "")
    if not root: raise HttpError(503, "NITRO_DIR is not set for the web service, so Storigen does not know where the Nitro files are")
    if not os.path.isdir(root): raise HttpError(404, "The Nitro folder is not reachable now (not mounted?)")
    exts = tuple(e.strip().lower() for e in os.getenv("NITRO_EXTS", ".mxf").split(",") if e.strip()) or (".mxf",)
    try: depth, back, ahead = int(os.getenv("NITRO_SCAN_DEPTH", "3") or 3), int(os.getenv("NITRO_SCAN_DAYS_BACK", "1") or 1), int(os.getenv("NITRO_SCAN_DAYS_AHEAD", "1") or 1)
    except ValueError: depth, back, ahead = 3, 1, 1
    pats = [x.strip() for x in os.getenv("NITRO_DATE_PATH", "").split("|") if x.strip()]
    want = norm_name(re.sub(r"\.[A-Za-z0-9]{2,4}$", "", (title or "").strip()))
    if not want: return None, "nothing (the clip has no usable name)"
    roots = [root]
    if pats:
        today = dt.date.today(); roots = []
        for k in sorted(range(-back, ahead + 1), key=abs):                      # today first, then the days around it
            for pat in pats:
                p = os.path.join(root, (today + dt.timedelta(days=k)).strftime(pat))
                if os.path.isdir(p) and p not in roots: roots.append(p)
        if not roots: return None, "no day folder for today under the Nitro folder (NITRO_DATE_PATH=%s)" % "|".join(pats)
    best = []
    def walk(d, level):
        try: it = list(os.scandir(d))
        except OSError: return
        for e in it:
            if e.name.startswith("."): continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if level < depth: walk(e.path, level + 1)
                elif e.name.lower().endswith(exts) and norm_name(os.path.splitext(e.name)[0]) == want: best.append((e.stat().st_mtime, e.path))
            except OSError: continue
    for r in roots:
        walk(r, 0)
        if best: break                                                          # found in the first (closest) day folder: no need to look further
    where = ", ".join(os.path.basename(x.rstrip("/\\")) or x for x in roots)
    return (max(best)[1] if best else None), where

def open_stream(path):
    if not enabled(): raise HttpError(404, "Preview is switched off (PREVIEW_ENABLED=0)")
    if not ffmpeg(): raise HttpError(503, "ffmpeg is not installed on the Storigen machine")
    real = check_path(path); sem = _slot()
    if not sem.acquire(blocking=False): raise HttpError(429, "Another preview is running. Try again in a moment")
    return Stream(real, sem)

class Stream:
    ctype = "video/mp4"
    def __init__(self, path, sem): self.path, self.sem, self.done = path, sem, False
    def release(self):
        if not self.done: self.done = True; self.sem.release()
    def run(self, out):
        h, cap = int(os.getenv("PREVIEW_HEIGHT", "360") or 360), int(os.getenv("PREVIEW_MAX_SECONDS", "900") or 900)
        # v10.3.1: broadcast MXF is awkward for a browser: several audio tracks, a timecode data track, interlaced pictures, a start time that is not 0.
        # So take ONE picture and ONE sound track, drop data/subtitle tracks, de-interlace only if flagged, start both at 0 and cut a keyframe every 2 s (small fragments start playing at once).
        cmd = [ffmpeg(), "-nostdin", "-v", "error", "-fflags", "+genpts", "-threads", os.getenv("PREVIEW_THREADS", "2"), "-i", self.path,
               "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-vf", "yadif=deint=interlaced,scale=-2:%d,setpts=PTS-STARTPTS" % h,
               "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-profile:v", "main", "-crf", "30", "-pix_fmt", "yuv420p", "-g", "50", "-keyint_min", "50", "-sc_threshold", "0",
               "-af", "aresample=async=1:first_pts=0", "-c:a", "aac", "-b:a", "64k", "-ac", "2", "-ar", "48000", "-avoid_negative_ts", "make_zero", "-max_muxing_queue_size", "1024", "-write_tmcd", "0", "-map_metadata", "-1",
               "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", "pipe:1"]
        kw = {"creationflags": 0x4000} if sys.platform == "win32" else {"preexec_fn": lambda: os.nice(10)}      # below normal priority: the poller and watcher come first
        try: p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, **kw)
        except OSError: self.release(); return
        timer = threading.Timer(cap, p.kill); timer.daemon = True; timer.start()
        try:
            fd = p.stdout.fileno()
            while True:
                b = os.read(fd, 65536)
                if not b: break
                out.write(b); out.flush()
        except OSError: pass                                  # the browser closed the page: stop converting at once
        finally:
            timer.cancel(); p.kill(); p.wait(); self.release()
