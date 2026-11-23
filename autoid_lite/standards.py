"""v10.16.0 AI standards check: violence, sexual content and heartbreak (distress) that is NOT blurred, flagged for a person to look at.
On demand only (a button on a clip on Nitro) and only while an admin has switched it on (Users > Features; OFF until then), because still frames of possibly graphic footage go to Groq, an outside service.
ffmpeg cuts small stills straight into memory (about one every 2 s, at most STANDARDS_MAX_FRAMES, 30 by default), they go to Groq's vision model in batches of 5, and the answer is a flag list with times and the frames. Nothing is stored.
This is a help for the desk, not a gate: the model can miss things and misjudge "blurred enough". It is told to answer "visible" when unsure, a batch it cannot read or that Groq refuses is listed as NOT CHECKED (never as fine),
and the result never says a clip is clear. parse_batch() and judge() are pure functions, tested without ffmpeg or the network."""
from __future__ import annotations
import base64, json, os, re, time
from .common import HttpError
from . import clipsummary, preview, quality

CATS = {"violence": "graphic violence: blood, wounds, injured or dead people, bodies, a weapon being used on someone, a beating or a fight with visible injury",
        "sexual": "nudity or sexual content: exposed genitals, buttocks or breasts, or a sexual act",
        "distress": "heartbreaking human suffering: a person crying out or breaking down in grief or pain, the bereaved at a body, an injured or dead child, a close-up of a victim in anguish"}
VALUES = ("none", "blurred", "visible")
BATCH = 5                                                  # Groq accepts at most 5 pictures in one request


def available(): return bool(clipsummary.key())
def categories():
    got = [c.strip() for c in (os.getenv("STANDARDS_CATEGORIES") or "violence,sexual,distress").split(",")]
    return [c for c in got if c in CATS] or list(CATS)
def max_frames(): return max(3, min(60, int(float(os.getenv("STANDARDS_MAX_FRAMES", "30") or 30))))
def height(): return max(240, min(720, int(float(os.getenv("STANDARDS_HEIGHT", "480") or 480))))
def max_seconds(): return max(20, min(900, int(float(os.getenv("STANDARDS_MAX_SECONDS", "240") or 240))))


def plan(duration, every=2.0, cap=None):
    """Frame times: one every `every` seconds (the middle of each slot), but never more than `cap`: a long clip gets a wider gap (reported back). -> (times, interval)"""
    cap = cap or max_frames(); d = float(duration or 0)
    if d <= 0: return [0.0], every
    n = max(1, min(cap, int(d // every) or 1)); iv = d / n
    return [round(iv * (i + 0.5), 2) for i in range(n)], round(iv, 2)


def prompt(n, cats=None, note=None):
    cats = cats or categories(); note = (note if note is not None else os.getenv("STANDARDS_NOTE") or "").strip()[:600]
    lines = "\n".join("- %s: %s" % (c, CATS[c]) for c in cats)
    ex = '{"frames":[' + ",".join('{"n":%d,%s,"note":"at most 12 words on what matters"}' % (i + 1, ",".join('"%s":"none"' % c for c in cats)) for i in range(min(n, 2))) + (",..." if n > 2 else "") + "]}"
    return ("You are helping a TV news desk check video before it goes on air. The %d attached pictures are frames, in order, numbered 1 to %d, from one video clip.\n"
            "For EACH frame and EACH category below answer exactly one of: \"none\" (that kind of content is not in the frame), \"blurred\" (it is there, but the sensitive part is blurred, pixelated or covered so it cannot be made out), "
            "\"visible\" (it is there and clearly visible, not blurred).\nCategories:\n%s\n%sIf you are not sure whether something is blurred enough, answer \"visible\". Describe only what you can see; do not name any person.\n"
            "Reply with ONLY JSON, nothing else, with exactly %d entries in \"frames\", like: %s") % (n, n, lines, ("The newsroom's own standard: " + note + "\n") if note else "", n, ex)


def parse_batch(text, n, cats):
    """The model's text -> a list of n items, each {cat: none|blurred|visible, note} or None (could not be read). Strict: wrong count, a missing frame number or a value outside none/blurred/visible makes THAT frame (or the whole batch) unreadable, never 'none'."""
    t = (text or "").strip(); t = re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.I | re.M).strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a: return [None] * n
    try: fr = json.loads(t[a:b + 1]).get("frames")
    except (ValueError, AttributeError): return [None] * n
    if not isinstance(fr, list): return [None] * n
    out = [None] * n
    for x in fr:
        if not isinstance(x, dict) or not isinstance(x.get("n"), int) or not 1 <= x["n"] <= n or out[x["n"] - 1] is not None: continue
        if not all(isinstance(x.get(c), str) and x[c].strip().lower() in VALUES for c in cats): continue
        out[x["n"] - 1] = dict({c: x[c].strip().lower() for c in cats}, note=" ".join(str(x.get("note") or "").split())[:120])
    return out


def judge(frames, cats, interval=2.0):
    """Pure. frames = [{t, res: {cat: value, note} | None, error?}] in time order -> {flags, counts}. A flag is a run of neighbouring frames with the same category and verdict:
    visible = NOT BLURRED (red), blurred = the AI says it is blurred (amber: check by eye), unchecked = the frames could not be read (amber). 'none' is never listed."""
    flags, open_ = [], {}
    def close(k):
        if k in open_: flags.append(open_.pop(k))
    for i, f in enumerate(frames):
        seen = set()
        if f["res"] is None: items = [("all", "unchecked", f.get("error") or "the AI answer for this frame could not be read")]
        else: items = [(c, f["res"][c], f["res"].get("note") or "") for c in cats if f["res"][c] != "none"]
        for c, v, note in items:
            k = (c, v); seen.add(k)
            if k in open_ and open_[k]["end"] == i - 1: o = open_[k]; o["last"] = f["t"]; o["end"] = i; o["frames"] += 1; o["note"] = o["note"] or note
            else:
                close(k); open_[k] = {"category": c, "verdict": v, "t": f["t"], "last": f["t"], "start": i, "end": i, "frames": 1, "note": note}
        for k in [k for k in open_ if k not in seen]: close(k)
    for k in list(open_): close(k)
    order = {"visible": 0, "unchecked": 1, "blurred": 2}
    flags.sort(key=lambda x: (order[x["verdict"]], x["t"]))
    return {"flags": flags, "counts": {"frames": len(frames), "unchecked": sum(1 for f in frames if f["res"] is None), "visible": sum(1 for x in flags if x["verdict"] == "visible"), "blurred": sum(1 for x in flags if x["verdict"] == "blurred")}}


def check(path, opener=None, now=time.time):
    """Cut the frames of a file inside NITRO_DIR, ask Groq, judge. Returns the result dict (flags with pictures, counts, interval, model, ai_error). Raises HttpError for the user-facing problems."""
    if not available(): raise HttpError(503, "The AI standards check needs GROQ_API_KEY in autoid.env (it is empty)")
    if not preview.ffmpeg() or not quality.ffprobe(): raise HttpError(503, "ffmpeg / ffprobe is not installed on the Storigen machine")
    real = preview.check_path(path); cats = categories(); sem = quality._job_slot()
    try:
        info = quality.probe(real)
        if not info.get("has_video"): raise HttpError(422, "ffprobe could not read a picture from this file (it may still be copying)")
        ts, iv = plan(info.get("duration_s")); h = height(); got = [(t, clipsummary.grab(real, t, h)) for t in ts]
    finally: sem.release()
    if not any(j for _, j in got): raise HttpError(422, "No picture could be taken from this file (it may still be copying)")
    frames, err, stop, t0 = [], None, False, now()
    for s in range(0, len(got), BATCH):
        part = got[s:s + BATCH]; send = [(t, j) for t, j in part if j]
        res = [None] * len(part); why = "the picture could not be taken from the file"
        if send and not stop and now() - t0 < max_seconds():
            if not clipsummary._rate_ok(): err = err or "The hourly limit for AI calls is reached (GROQ_MAX_PER_HOUR): the rest was not checked"; stop = True
            else:
                content = [{"type": "text", "text": prompt(len(send), cats)}] + [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(j).decode()}} for _, j in send]
                try:
                    data = clipsummary.post_groq({"model": clipsummary.model(), "messages": [{"role": "user", "content": content}], "temperature": 0.1, "max_tokens": 900}, timeout=45, opener=opener)
                    text = data["choices"][0]["message"]["content"]
                except HttpError as e:
                    if getattr(e, "fatal", False): raise                    # a wrong key or an unusable model: nothing will work, say so
                    err = err or e.detail; stop = True; why = "the AI could not be reached or refused this batch"
                except (KeyError, IndexError, TypeError): text = ""; why = "the AI sent an answer that could not be read"
                else:
                    parsed = parse_batch(text, len(send), cats); it = iter(parsed)
                    res = [next(it) if j else None for _, j in part]
                    if all(x is None for x in parsed): why = "the AI did not answer in the expected form (it may have refused these pictures)"
                    else: why = "the AI's answer for this frame was incomplete"
        elif send:
            why = "not sent: " + ("the time limit was reached" if not stop else "an earlier AI call failed")
            if not stop: err = err or "The time limit for the check (STANDARDS_MAX_SECONDS) was reached: the rest was not checked"; stop = True
        for (t, j), r in zip(part, res): frames.append({"t": t, "res": r, "jpeg": j, "error": why if j else "the picture could not be taken from the file"})
    out = judge(frames, cats, iv); keep = {}
    for k, x in enumerate(out["flags"]):                                   # a picture for the first frames of the flags, red first, at most 12
        if len(keep) < 12:
            j = frames[x["start"]]["jpeg"]
            if j: keep[k] = base64.b64encode(j).decode()
    for k, x in enumerate(out["flags"]): x.pop("start", None); x.pop("end", None); x["jpeg_b64"] = keep.get(k)
    out.update({"duration_s": info.get("duration_s"), "interval_s": iv, "categories": cats, "model": clipsummary.model()})
    if err: out["ai_error"] = err
    return out
