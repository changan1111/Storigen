"""v10.12.0 Clip frames and the AI one-line summary. On demand only (a button on the clip). Nothing is stored: ffmpeg cuts a few small pictures straight into memory, they go to the
browser, and - only when the person presses "Describe with AI" - to Groq's vision model, which answers with one sentence and a few tags. No file, no cache, no database row.
The Groq key is read from GROQ_API_KEY (autoid.env / environment); it is never sent to the browser, never logged and never put in an error message.
GROQ_VISION_MODEL names the model (it can change at Groq: see console.groq.com/docs/vision). Groq accepts at most 5 pictures in one request."""
from __future__ import annotations
import base64, socket, ssl, json, os, re, subprocess, sys, threading, time, urllib.error, urllib.request
from .common import HttpError
from . import preview, quality

URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
PROMPT = ("These %d pictures are frames taken evenly, in order, from one short TV news video clip. In ONE plain sentence of at most 25 words, say what the clip shows. "
          "Describe only what you can see; do not name any person and do not guess who anyone is. Then write a line starting with 'Tags:' and 3 to 5 short lowercase tags separated by commas.")
_hits = []; _hlock = threading.Lock()


def key(): return (os.getenv("GROQ_API_KEY") or "").strip()
def ai_available(): return bool(key()) and os.getenv("CLIP_SUMMARY", "1") != "0"
def frames_enabled(): return os.getenv("CLIP_FRAMES", "1") != "0"
def model(): return (os.getenv("GROQ_VISION_MODEL") or DEFAULT_MODEL).strip()
_learned = [None]      # v10.18.3: the picture limit Groq reported for this model ("supports up to 3 images"), remembered until restart
def max_images():
    """Most pictures one Groq request may carry: GROQ_MAX_IMAGES (default 5), lowered to whatever Groq itself reported for the model."""
    n = max(1, int(float(os.getenv("GROQ_MAX_IMAGES", "5") or 5)))
    return min(n, _learned[0]) if _learned[0] else n
def n_frames(): return min(5, max(1, int(float(os.getenv("CLIP_FRAMES_COUNT", "4") or 4))))
def spread(items, n):
    """n items taken evenly across the list, in order (all of them when there are no more than n)."""
    if len(items) <= n: return list(items)
    if n == 1: return [items[len(items) // 2]]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def times(duration, n):
    """n moments spread evenly over the clip (the middle of each equal part), never the very first or last frame (those are often black)."""
    d = float(duration or 0)
    if d <= 0: return [0.0]
    return [round(d * (i + 0.5) / n, 2) for i in range(n)]


def grab(path, t, height, timeout=25):
    """One JPEG of the file at second t, in memory. Returns bytes or None."""
    cmd = [preview.ffmpeg(), "-nostdin", "-v", "error", "-ss", str(t), "-i", path, "-an", "-sn", "-dn", "-frames:v", "1", "-vf", "yadif=deint=interlaced,scale=-2:%d" % height,
           "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
    try: out = subprocess.run(cmd, capture_output=True, timeout=timeout, **quality._low_priority()).stdout
    except (OSError, subprocess.SubprocessError): return None
    return out if out[:2] == b"\xff\xd8" else None


def parse_answer(text):
    """The model's text -> {summary, tags}. Tolerant: the first sentence is the summary; a 'Tags:' line gives the tags."""
    t = (text or "").strip(); tags = []
    m = re.search(r"(?im)^\s*\**tags\**\s*:\s*(.+)$", t)
    if m: tags = [x.strip().strip("#.").lower() for x in m.group(1).split(",") if x.strip()][:6]; t = t[:m.start()].strip()
    t = re.sub(r"(?i)^\s*(summary|description)\s*:\s*", "", t).strip()
    return {"summary": " ".join(t.split())[:400], "tags": tags}


def _rate_ok():
    """A simple ceiling so the key is not used up by accident: GROQ_MAX_PER_HOUR calls (default 60) for the whole server."""
    cap = int(float(os.getenv("GROQ_MAX_PER_HOUR", "60") or 60)); now = time.time()
    with _hlock:
        _hits[:] = [h for h in _hits if now - h < 3600]
        if len(_hits) >= cap: return False
        _hits.append(now); return True


def _fatal(e): e.fatal = True; return e      # a problem that will repeat on every call (wrong key, unusable model): callers that make several calls stop at once


def _ctx():
    """v10.18.1: the certificates used to check api.groq.com. A python.org Python on a Mac has NO certificates of its own until 'Install Certificates.command' is run, so the Groq call failed
    ('certificate verify failed') even though curl, which uses the Mac's own, worked. Order: SSL_CERT_FILE (if set, Python already uses it) -> the certifi package if installed -> the Mac / Linux system bundle."""
    if os.getenv("SSL_CERT_FILE"): return None
    try:
        import certifi; return ssl.create_default_context(cafile=certifi.where())
    except Exception: pass
    for f in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
        if os.path.isfile(f):
            try: return ssl.create_default_context(cafile=f)
            except Exception: continue
    return None


def _opener():
    """v10.17.0: urllib already follows HTTPS_PROXY / HTTP_PROXY of the machine; GROQ_PROXY (for example http://proxy.newsroom:3128) sends only the Groq calls through a proxy."""
    px = (os.getenv("GROQ_PROXY") or "").strip(); hs = []
    if px: hs.append(urllib.request.ProxyHandler({"http": px, "https": px}))
    c = _ctx()
    if c is not None: hs.append(urllib.request.HTTPSHandler(context=c))
    return urllib.request.build_opener(*hs)


def why_unreachable(e):
    """A plain reason for a failed connection, so IT knows what to open. Never contains the key."""
    r = getattr(e, "reason", e); t = type(r).__name__; txt = str(r).lower()
    if isinstance(r, socket.gaierror) or "name or service not known" in txt or "nodename nor servname" in txt or "getaddrinfo" in txt or "temporary failure in name resolution" in txt: return "the name api.groq.com could not be found (DNS blocked or no internet)"
    if isinstance(r, socket.timeout) or "timed out" in txt: return "no answer in time (a firewall is probably dropping api.groq.com on port 443)"
    if isinstance(r, ssl.SSLCertVerificationError) or "certificate verify failed" in txt: return "this machine's Python does not trust the certificate of api.groq.com (on a Mac with Python from python.org: run 'Install Certificates.command' in /Applications/Python 3.x, or set SSL_CERT_FILE; behind a proxy that inspects traffic: its certificate is needed; or the clock is wrong)"
    if isinstance(r, ssl.SSLError) or "certificate" in txt or "ssl" in txt: return "a secure connection could not be made (a proxy or firewall that inspects traffic, or a wrong clock)"
    if isinstance(r, ConnectionRefusedError) or "refused" in txt: return "the connection was refused (a firewall or proxy)"
    return "%s" % t


def post_groq(body, timeout=40, opener=None):
    """POST one chat request to Groq and return the parsed answer. Every problem becomes an HttpError with a plain message that never contains the key. opener: a stand-in for urlopen in tests."""
    if not key(): raise HttpError(503, "The AI is not set up: GROQ_API_KEY is empty on the Storigen machine")
    req = urllib.request.Request((os.getenv("GROQ_URL") or URL).strip(), data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", "Authorization": "Bearer " + key(), "User-Agent": "Storigen/10.18"})
    try:
        with (opener or _opener().open)(req, timeout=timeout) as r: return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        code = e.code
        if code in (401, 403): raise _fatal(HttpError(502, "Groq did not accept the key (GROQ_API_KEY). Check it at console.groq.com"))
        if code == 404 or code == 400:      # v10.18.2: say Groq's OWN reason (it may be the model, or the request itself); it never contains the key
            try: why = str(((json.loads(e.read().decode("utf-8", "replace")) or {}).get("error") or {}).get("message") or "")[:300].replace(key(), "***") if key() else ""
            except Exception: why = ""
            m = re.search(r"up to (\d+) images?", why or "", re.I)
            if m: _learned[0] = max(1, int(m.group(1)))
            raise _fatal(HttpError(502, "Groq refused the request (HTTP %s) for the model %s%s. Set GROQ_VISION_MODEL to a model your key can use: run the list command in docs/CHANGES_v10180.md, or see console.groq.com/docs/vision" % (code, model(), (": " + why) if why else "")))
        if code == 429: raise HttpError(429, "Groq says: too many requests right now. Try again in a minute")
        raise HttpError(502, "Groq answered with an error (%s). Try again" % code)
    except (urllib.error.URLError, OSError, ValueError) as e: raise HttpError(502, "Groq could not be reached from the Storigen machine (internet / firewall): %s. The pictures are shown without a description" % why_unreachable(e))


def ask_groq(jpegs, timeout=40, opener=None):
    """Send the pictures to Groq and return {summary, tags}. opener: a stand-in for urllib's urlopen in tests."""
    if not ai_available(): raise HttpError(503, "The AI summary is not set up: GROQ_API_KEY is empty on the Storigen machine")
    if not _rate_ok(): raise HttpError(429, "The hourly limit for AI summaries is reached (GROQ_MAX_PER_HOUR). Try again later")
    def send(pics):
        content = [{"type": "text", "text": PROMPT % len(pics)}] + [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(j).decode()}} for j in pics]
        return post_groq({"model": model(), "messages": [{"role": "user", "content": content}], "temperature": 0.2, "max_tokens": 220}, timeout, opener)
    pics = spread(jpegs, max_images())       # v10.18.3: never more pictures than the model accepts (some models allow only 3)
    try: data = send(pics)
    except HttpError:
        if len(spread(jpegs, max_images())) < len(pics): data = send(spread(jpegs, max_images()))   # Groq just told us a lower limit: try once more with that many
        else: raise
    try: text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError): raise HttpError(502, "Groq sent an answer Storigen could not read")
    out = parse_answer(text)
    if not out["summary"]: raise HttpError(502, "Groq sent an empty description")
    out["model"] = model(); return out


def describe(path, ai=True, opener=None):
    """Frames of a file inside NITRO_DIR (+ the AI sentence when ai=True). Returns {duration_s, frames: [{t, jpeg_b64}], summary?, tags?, ai_error?}. Nothing is stored."""
    if not frames_enabled(): raise HttpError(404, "Clip frames are switched off (CLIP_FRAMES=0)")
    if not preview.ffmpeg() or not quality.ffprobe(): raise HttpError(503, "ffmpeg / ffprobe is not installed on the Storigen machine")
    real = preview.check_path(path)
    if ai and not ai_available(): raise HttpError(503, "The AI summary is not set up: GROQ_API_KEY is empty on the Storigen machine")
    sem = quality._job_slot()
    try:
        info = quality.probe(real)
        if not info.get("has_video"): raise HttpError(422, "ffprobe could not read a picture from this file (it may still be copying)")
        h = int(os.getenv("CLIP_FRAMES_HEIGHT", "360") or 360); ts = times(info.get("duration_s"), n_frames()); got = []
        for t in ts:
            j = grab(real, t, h)
            if j: got.append((t, j))
        if not got: raise HttpError(422, "No picture could be taken from this file (it may still be copying)")
    finally: sem.release()
    out = {"duration_s": info.get("duration_s"), "frames": [{"t": t, "jpeg_b64": base64.b64encode(j).decode()} for t, j in got]}
    if ai:
        try: out.update(ask_groq([j for _, j in got], opener=opener))
        except HttpError as e: out["ai_error"] = e.detail      # the pictures are still useful: the person sees them and the reason there is no sentence
    return out
