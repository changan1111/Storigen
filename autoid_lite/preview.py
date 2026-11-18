"""v10.1.0: play a clip from the Nitro ONAIR folder in the dashboard. Nothing is stored: every Play converts the MXF to a small H.264 stream with ffmpeg
and sends it straight to the browser (no cache, no temp file, nothing written in the project). It only runs when someone clicks Play, at low CPU
priority, one at a time by default (PREVIEW_MAX_JOBS), and it stops the moment the browser stops watching."""
import os, shutil, subprocess, sys, threading
from .common import HttpError

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
