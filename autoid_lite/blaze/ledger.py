"""Tool-vs-desk agreement ledger (stdlib only). Trust comes from numbers: for every clip, what the tool WOULD have attached against what the
desk ACTUALLY attached in Blaze. Used by blaze_poll.py; never talks to Blaze itself.

Outcome of one clip (the registry says which story it belongs to; the ledger remembers the tool's plan and every Blaze story where a clip with our ID was seen):
  AGREE        the desk attached the file the tool would have attached, in the story the registry expects
  DISAGREE     the desk attached a different file than the tool would have
  TOOL_MISSED  the desk attached it but the tool never found the file in Blaze's media list
  WRONG_STORY  a clip with this ID sits in a different story than the registry expects
  DUPLICATE    the same file attached twice, or in two stories
  OVERDUE      the tool found the file long ago and nobody has attached it
  WAITING      file found recently, not attached yet (normal)
  NO_FILE      nothing exported yet (left out of the rate)
Agreement rate = AGREE / (AGREE + DISAGREE + TOOL_MISSED + WRONG_STORY + DUPLICATE). OVERDUE and WAITING are listed but not counted against it."""
from __future__ import annotations
import csv, html as _html, sqlite3, time
from pathlib import Path

DECIDED = ("AGREE", "DISAGREE", "TOOL_MISSED", "WRONG_STORY", "DUPLICATE")
ORDER = ("AGREE", "DISAGREE", "TOOL_MISSED", "WRONG_STORY", "DUPLICATE", "OVERDUE", "WAITING", "NO_FILE")

SCHEMA = """
CREATE TABLE IF NOT EXISTS plan(display_id TEXT PRIMARY KEY, story_id TEXT, show_id TEXT, media_id TEXT, media_title TEXT, planned_at REAL);
CREATE TABLE IF NOT EXISTS seen(display_id TEXT, story_id TEXT, show_id TEXT, media_id TEXT, title TEXT, n INTEGER, first_seen REAL, PRIMARY KEY(display_id, story_id, media_id));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS live(display_id TEXT PRIMARY KEY, story_id TEXT, show_id TEXT, media_id TEXT, media_title TEXT, sent_at REAL, status TEXT, blaze_clip_id TEXT, error TEXT);
"""

class Ledger:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(str(path), isolation_level=None, timeout=30); self.c.row_factory = sqlite3.Row; self.c.executescript(SCHEMA)
    def has_plan(self, display_id): return self.c.execute("SELECT 1 FROM plan WHERE display_id=?", (display_id,)).fetchone() is not None
    def plan(self, display_id, story, show, media_id, title, now=None):
        now = now or time.time(); r = self.c.execute("SELECT media_id FROM plan WHERE display_id=?", (display_id,)).fetchone()
        if r is None: self.c.execute("INSERT INTO plan VALUES(?,?,?,?,?,?)", (display_id, story, show, str(media_id), title, now))
        elif r["media_id"] != str(media_id): self.c.execute("UPDATE plan SET story_id=?, show_id=?, media_id=?, media_title=?, planned_at=? WHERE display_id=?", (story, show, str(media_id), title, now, display_id))
    def seen(self, display_id, story, show, media_id, title, n=1, now=None):
        now = now or time.time()
        self.c.execute("INSERT INTO seen VALUES(?,?,?,?,?,?,?) ON CONFLICT(display_id, story_id, media_id) DO UPDATE SET n=MAX(n, excluded.n), title=excluded.title",
                       (display_id, str(story), str(show), str(media_id), title, n, now))
    def plan_of(self, display_id): return self.c.execute("SELECT * FROM plan WHERE display_id=?", (display_id,)).fetchone()
    def seen_of(self, display_id): return self.c.execute("SELECT * FROM seen WHERE display_id=?", (display_id,)).fetchall()
    # ---- live attach: one row per clip, written BEFORE the call is sent, so a clip can never be sent twice (a crash leaves the row, and the restart sees it)
    def live_start(self, display_id, story, show, media_id, title, now=None):
        """True only for the first attempt of this clip ever. A failed or unclear attempt is never repeated unless a person runs live-retry."""
        cur = self.c.execute("INSERT OR IGNORE INTO live VALUES(?,?,?,?,?,?,?,?,?)", (display_id, str(story), str(show), str(media_id), title, now or time.time(), "SENDING", None, None))
        return cur.rowcount == 1
    def live_finish(self, display_id, status, clip_id=None, error=None):
        self.c.execute("UPDATE live SET status=?, blaze_clip_id=COALESCE(?, blaze_clip_id), error=? WHERE display_id=?", (status, clip_id, error, display_id))
    def live_of(self, display_id): return self.c.execute("SELECT * FROM live WHERE display_id=?", (display_id,)).fetchone()
    def live_rows(self, limit=20): return self.c.execute("SELECT * FROM live ORDER BY sent_at DESC LIMIT ?", (limit,)).fetchall()
    def live_count_since(self, ts): return self.c.execute("SELECT COUNT(*) FROM live WHERE sent_at>=?", (ts,)).fetchone()[0]
    def live_clear(self, display_id): return self.c.execute("DELETE FROM live WHERE display_id=?", (display_id,)).rowcount
    def get(self, k, d=None): r = self.c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone(); return r["v"] if r else d
    def put(self, k, v): self.c.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    def delete(self, k): self.c.execute("DELETE FROM meta WHERE k=?", (k,))

def classify(clip, plan, seen, now, overdue_s=900):
    """-> (status, detail). clip: registry row (display_id, blaze_story_id). plan: ledger plan row or None. seen: ledger seen rows."""
    story = str(clip["blaze_story_id"]); right = [s for s in seen if str(s["story_id"]) == story]; other = [s for s in seen if str(s["story_id"]) != story]
    if right:
        if other: return "DUPLICATE", "also attached in story %s" % ", ".join(sorted({str(s["story_id"]) for s in other}))
        if len({s["media_id"] for s in right}) > 1 or any((s["n"] or 1) > 1 for s in right): return "DUPLICATE", "attached more than once in the story"
        s = right[0]
        if plan is None: return "TOOL_MISSED", "desk attached media %s; the tool never found the file in the media list" % s["media_id"]
        if str(plan["media_id"]) != str(s["media_id"]): return "DISAGREE", "desk attached media %s, the tool would have attached %s (%s)" % (s["media_id"], plan["media_id"], plan["media_title"])
        return "AGREE", ""
    if other: return "WRONG_STORY", "clip is in story %s, the registry expects %s" % (", ".join(sorted({str(s["story_id"]) for s in other})), story)
    if plan is not None:
        age = now - plan["planned_at"]
        return ("OVERDUE", "file found %d min ago, still not attached" % (age // 60)) if age > overdue_s else ("WAITING", "file found, not attached yet")
    return "NO_FILE", ""

def build(ledger, rows, now=None, overdue_s=900):
    """Classify every registry row of one day. -> (list of result dicts, summary dict)."""
    now = now or time.time(); out = []
    for r in rows:
        if r.get("deleted"): continue
        p = ledger.plan_of(r["display_id"]); sn = ledger.seen_of(r["display_id"]); st, why = classify(r, p, sn, now, overdue_s)
        mine = [s for s in sn if str(s["story_id"]) == str(r["blaze_story_id"])] or sn
        out.append({"display_id": r["display_id"], "show": r["blaze_rundown_id"], "slug_id": r.get("slug_id") or "", "row": "" if r.get("position") is None else r.get("position"), "story": r["blaze_story_id"], "title": r.get("slug") or "",
                    "status": st, "detail": why, "tool_media": p["media_id"] if p else "", "tool_file": p["media_title"] if p else "",
                    "tool_planned_at": time.strftime("%H:%M:%S", time.localtime(p["planned_at"])) if p else "",
                    "desk_media": mine[0]["media_id"] if mine else "", "desk_first_seen": time.strftime("%H:%M:%S", time.localtime(mine[0]["first_seen"])) if mine else ""})
    counts = {k: sum(1 for o in out if o["status"] == k) for k in ORDER}; decided = sum(counts[k] for k in DECIDED)
    return out, {"counts": counts, "decided": decided, "rate": (counts["AGREE"] / decided) if decided else None}

def text(day, results, summary):
    c = summary["counts"]; lines = ["Tool vs desk, day %s" % day, "  " + ", ".join("%s %d" % (k, c[k]) for k in ORDER if c[k])]
    lines.append("  agreement: " + ("%.0f%% of %d attached clips" % (100 * summary["rate"], summary["decided"]) if summary["rate"] is not None else "nothing to compare yet"))
    for o in results:
        if o["status"] not in ("AGREE", "NO_FILE", "WAITING"): lines.append("  %-11s %-30s story %s  %s" % (o["status"], o["display_id"], o["story"], o["detail"]))
    return "\n".join(lines)

def write_csv(path, results):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cols = ["display_id", "show", "slug_id", "row", "story", "title", "status", "detail", "tool_media", "tool_file", "tool_planned_at", "desk_media", "desk_first_seen"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); [w.writerow(o) for o in results]


# ---------------------------------------------------------------- the styled report page (same look as the dashboard)
GOOD, LOOK, QUIET = ("AGREE",), ("DISAGREE", "TOOL_MISSED", "WRONG_STORY", "DUPLICATE", "OVERDUE"), ("WAITING", "NO_FILE")
MEANING = {"AGREE": "same file as the editor", "DISAGREE": "editor attached a different file", "TOOL_MISSED": "editor attached, the tool found no file", "WRONG_STORY": "clip is in another story",
           "DUPLICATE": "attached twice or in two stories", "OVERDUE": "file found, still not attached", "WAITING": "file found, not attached yet", "NO_FILE": "no file in Blaze yet"}
CSS = """:root{--bg:#f3f6fb;--fg:#13203a;--mut:#5b6b85;--card:#fff;--bd:#dde4f0;--nav:#13233f;--ac:#2563eb;--ok:#15803d;--okb:#dcf3e4;--bad:#b42323;--badb:#fbe3e3;--wn:#92520a;--wnb:#fdecd0;--in:#1d4ed8;--inb:#e0e9fd;--id:#5b6b85;--idb:#e8ebf1;
 box-sizing:border-box;padding-bottom:env(safe-area-inset-bottom,0px)}
@media(prefers-color-scheme:dark){:root{--bg:#0e1522;--fg:#e6ebf5;--mut:#9aa8c2;--card:#16202f;--bd:#27344a;--nav:#0a1220;--ac:#7fb0f5;--ok:#7bd69c;--okb:#14301f;--bad:#f29d9d;--badb:#3b1b1b;--wn:#efb870;--wnb:#392a10;--in:#93b8f5;--inb:#17263f;--id:#9aa8c2;--idb:#232e40}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{background:var(--nav);color:#fff;padding:calc(.9rem + env(safe-area-inset-top,0px)) 1rem .9rem}
.hd{max-width:68rem;margin:auto;display:flex;gap:.8rem;align-items:center;flex-wrap:wrap;justify-content:space-between}
.hd b{font-size:1.15rem;letter-spacing:.04em}.hd span{color:#b8c6e0;font-size:.82rem;display:block}
.pill{border:1px solid #3a557f;border-radius:999px;padding:.3rem .7rem;font-size:.78rem;font-weight:600;color:#cfe0ff}
main{max-width:68rem;margin:auto;padding:1rem 1rem 3rem}
h1{font-size:1.45rem;margin:.2rem 0}h2{font-size:1.1rem;margin:1.8rem 0 .5rem}.mut{color:var(--mut);font-size:.88rem}
a{color:var(--ac)}.nav{display:flex;gap:1rem;margin:.3rem 0 .8rem;font-size:.9rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr));gap:.6rem;margin:.8rem 0}
.c{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:.75rem .9rem}.c b{display:block;font-size:1.9rem;line-height:1.1}.c span{color:var(--mut);font-size:.8rem}.c.big b{color:var(--ac)}
.b{display:inline-block;font-weight:700;font-size:.72rem;letter-spacing:.03em;padding:.28rem .55rem;border-radius:999px;white-space:nowrap}
.AGREE{background:var(--okb);color:var(--ok)}.DISAGREE,.TOOL_MISSED,.WRONG_STORY,.DUPLICATE{background:var(--badb);color:var(--bad)}.OVERDUE{background:var(--wnb);color:var(--wn)}.WAITING{background:var(--inb);color:var(--in)}.NO_FILE{background:var(--idb);color:var(--id)}
.chips{display:flex;gap:.45rem;flex-wrap:wrap;margin:.6rem 0}.chips button{font:inherit;font-size:.88rem;border:1px solid var(--bd);background:var(--card);color:var(--fg);border-radius:999px;padding:.4rem .9rem;cursor:pointer}
.chips button[aria-pressed=true]{background:var(--ac);border-color:var(--ac);color:#fff}
.look{background:var(--card);border:1px solid var(--bd);border-left:5px solid var(--wn);border-radius:12px;padding:.5rem 1rem}.look p{margin:.55rem 0}
.show{font-size:.95rem;font-weight:700;margin:1.3rem 0 .5rem}.show span{color:var(--mut);font-weight:400}
.s{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:.85rem 1rem;margin:.55rem 0}
.s .t{display:flex;justify-content:space-between;gap:.6rem;align-items:flex-start}.s .t b{font-size:1.02rem}
.id{font:.84rem ui-monospace,Menlo,Consolas,monospace;color:var(--ac);word-break:break-all;margin:.3rem 0}.sm{color:var(--mut);font-size:.84rem}
.two{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin-top:.5rem}.two div{background:var(--bg);border-radius:10px;padding:.5rem .65rem;font-size:.84rem;word-break:break-word}.two small{display:block;color:var(--mut);font-size:.72rem;text-transform:uppercase;letter-spacing:.04em}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--bd);border-radius:14px}table{border-collapse:collapse;width:100%;min-width:34rem;font-size:.88rem}th,td{text-align:left;padding:.5rem .7rem;border-bottom:1px solid var(--bd)}th{color:var(--mut);font-size:.74rem;text-transform:uppercase}tr:last-child td{border:0}
.hide{display:none}.note{background:var(--wnb);color:var(--wn);border-radius:10px;padding:.5rem .8rem;font-size:.86rem;margin:.6rem 0}
@media(max-width:34rem){.two{grid-template-columns:1fr}}"""

def render_html(day, results, summary, names=None, five=None, mode="dry", generated=None, nav=None):
    """One self-contained, escaped HTML page for a day: header, counts, needs-a-look list, per-show story cards with tool-vs-editor, the last days. Every text from Blaze goes through escape()."""
    e = lambda x: _html.escape(str(x if x is not None else ""), quote=True); names = names or {}; c = summary["counts"]; rate = summary["rate"]
    look = [o for o in results if o["status"] in LOOK]
    cards = [("big", "%.0f%%" % (100 * rate) if rate is not None else "-", "agreement" + (": %d of %d attached clips" % (c["AGREE"], summary["decided"]) if rate is not None else ": nothing to compare yet")),
             ("", len(results), "clips"), ("", c["AGREE"], "AGREE: same file as the editor"), ("", len(look), "need a look"),
             ("", c["WAITING"] + c["NO_FILE"], "waiting for a file or the editor")]
    out = ["<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'><title>Auto-ID report %s</title><style>%s</style></head><body>" % (e(day), CSS),
           "<header><div class=hd><div><b>AUTO-ID</b><span>TOOL VS DESK REPORT</span></div><div class=pill>%s</div></div></header><main>" % e({"dry": "DRY RUN: nothing is sent to Blaze", "live": "LIVE ATTACH ON", "off": "ATTACH OFF"}.get(mode, mode))]
    out.append("<h1>Tool vs desk: %s</h1><div class=mut>Generated %s</div>" % (e(day), e(generated or time.strftime("%Y-%m-%d %H:%M:%S"))))
    n = nav or {}; links = ["<a href='/report/%s'>&larr; %s</a>" % (e(n["prev"]), e(n["prev"])) if n.get("prev") else "", "<a href='/report/%s'>%s &rarr;</a>" % (e(n["next"]), e(n["next"])) if n.get("next") else "", "<a href='/'>Dashboard</a>"]
    out.append("<div class=nav>%s</div>" % " ".join(x for x in links if x))
    if mode == "live": out.append("<div class=note>Live attach is on: clips the tool attached itself count as AGREE, so agreement no longer measures the tool against the editor for those clips.</div>")
    out.append("<div class=cards>" + "".join("<div class='c %s'><b>%s</b><span>%s</span></div>" % (k, e(v), e(t)) for k, v, t in cards) + "</div>")
    out.append("<div class=mut>Agreement counts only clips the editor attached (AGREE, DISAGREE, TOOL_MISSED, WRONG_STORY, DUPLICATE). OVERDUE, WAITING and NO_FILE are not scored.</div>")
    if look:
        out.append("<h2>Needs a look</h2><div class=look>" + "".join("<p><span class='b %s'>%s</span> <b>%s</b> story %s: %s</p>" % (e(o["status"]), e(o["status"]), e(o["display_id"]), e(o["story"]), e(o["detail"])) for o in look) + "</div>")
    out.append("<h2>All clips</h2><div class=chips id=ch><button aria-pressed=true data-f=all>All %d</button><button aria-pressed=false data-f=look>Needs a look %d</button><button aria-pressed=false data-f=ok>Agree %d</button><button aria-pressed=false data-f=quiet>Waiting %d</button></div>" % (len(results), len(look), c["AGREE"], c["WAITING"] + c["NO_FILE"]))
    shows = {}
    for o in results: shows.setdefault(o["show"], []).append(o)
    for sh, rows in shows.items():
        out.append("<div class=show>%s <span>show %s &middot; %d clips</span></div>" % (e(names.get(str(sh)) or "Show " + str(sh)), e(sh), len(rows)))
        for o in sorted(rows, key=lambda x: (x["row"] if isinstance(x["row"], int) else 10 ** 9, x["display_id"])):
            grp = "ok" if o["status"] in GOOD else "look" if o["status"] in LOOK else "quiet"
            tool = ("%s<br><span class=sm>planned %s &middot; media %s</span>" % (e(o["tool_file"]), e(o["tool_planned_at"]), e(o["tool_media"]))) if o["tool_media"] else "no file found yet"
            desk = ("media %s<br><span class=sm>first seen %s</span>" % (e(o["desk_media"]), e(o["desk_first_seen"]))) if o["desk_media"] else "not attached"
            out.append("<div class=s data-g=%s><div class=t><b>%s</b><span class='b %s' title='%s'>%s</span></div><div class=sm>%s%s</div><div class=id>%s</div><div class=sm>Blaze story %s</div>%s"
                       "<div class=two><div><small>Tool would attach</small>%s</div><div><small>Editor attached</small>%s</div></div></div>" % (
                       grp, e(o["title"] or o["display_id"]), e(o["status"]), e(MEANING.get(o["status"], "")), e(o["status"]), ("Row %s" % e(o["row"])) if o["row"] != "" else "Row not known", "", e(o["display_id"]), e(o["story"]),
                       ("<div class=sm>%s</div>" % e(o["detail"])) if o["detail"] else "", tool, desk))
    if five:
        out.append("<h2>Last %d days</h2><div class=tw><table><thead><tr><th>Day</th><th>Clips</th><th>Agreement</th><th>Others</th></tr></thead><tbody>" % len(five))
        ag = dec = 0
        for f in five:
            ag += f["counts"]["AGREE"]; dec += f["decided"]; oth = ", ".join("%s %d" % (k, f["counts"][k]) for k in ORDER if f["counts"][k] and k != "AGREE")
            out.append("<tr><td>%s</td><td>%d</td><td>%s</td><td>%s</td></tr>" % (e(f["day"]), f["clips"], ("<b>%.0f%%</b> of %d" % (100 * f["rate"], f["decided"])) if f["rate"] is not None else "nothing to compare yet", e(oth)))
        out.append("<tr><td><b>Total</b></td><td>%d</td><td>%s</td><td></td></tr></tbody></table></div>" % (sum(f["clips"] for f in five), ("<b>%.0f%%</b> of %d" % (100 * ag / dec, dec)) if dec else "nothing to compare yet"))
    out.append("</main><script>(function(){var b=[].slice.call(document.querySelectorAll('#ch button')),s=[].slice.call(document.querySelectorAll('.s'));b.forEach(function(x){x.onclick=function(){b.forEach(function(y){y.setAttribute('aria-pressed',String(y===x))});var f=x.getAttribute('data-f');s.forEach(function(c){c.classList.toggle('hide',f!=='all'&&c.getAttribute('data-g')!==f)})}})})()</script></body></html>")
    return "".join(out)
