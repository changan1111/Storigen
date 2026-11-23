"""v10.12.0 Insights: four read-only helpers for the desk.
  GET /api/bot/checkname?rundown=&story=&name=   the Name coach: is this file name right, and if not, why and what to use
  GET /api/clips/<id>/quality                    on demand: black / frozen / silence / loudness / shape / length of the Nitro file (ffmpeg, nothing stored)
  GET /api/clips/<id>/frames?ai=0|1              on demand: a few small pictures of the clip; ai=1 also asks Groq for a one-line description (nothing stored)
  GET /api/analytics?days=7                      how long clips take, per bulletin: from the registry's own timestamps (no new data, nothing written)
None of them writes to the database, to Blaze or to disk."""
from __future__ import annotations
import datetime as dt, statistics
from .common import HttpError
from .ids import kind_of, suffix_on
from .coach import check_name
from . import quality, clipsummary, scanassets, standards

BAD = ("NEEDS_DESK", "QUARANTINED")


def _t(s):
    """An ISO time stored by the registry (UTC, ...Z) or a bulletin start (may have an offset) -> aware datetime, or None."""
    try: x = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError): return None
    return x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)


def _mins(a, b):
    a, b = _t(a), _t(b)
    return None if not a or not b else round((b - a).total_seconds() / 60, 1)


def _stat(v):
    v = sorted(x for x in v if x is not None and x >= 0)
    if not v: return {"n": 0, "median": None, "p90": None}
    p90 = v[min(len(v) - 1, int(round(0.9 * (len(v) - 1))))]
    return {"n": len(v), "median": round(statistics.median(v), 1), "p90": round(p90, 1)}


def summarise(rows, now=None):
    """Pure: rows = clip rows {day, version, state, created_at, on_nitro_at, attached_at, show, start_at, name_id}. -> totals, per-day, per-bulletin and the slowest clips."""
    def kind(r): return kind_of(r["version"]) or "base"
    def block(rs):
        att = [r for r in rs if r["state"] == "ATTACHED" and r.get("attached_at")]
        late = [r for r in att if _t(r.get("start_at")) and _t(r["attached_at"]) and _t(r["attached_at"]) > _t(r["start_at"])]
        return {"clips": len(rs), "attached": len(att), "waiting": sum(1 for r in rs if r["state"] in ("WAITING_FOR_CLIP", "EXPORTING", "VERIFIED", "ON_NITRO", "ATTACH_SUBMITTED")),
                "problem": sum(1 for r in rs if r["state"] in BAD), "late": len(late), "updates": sum(1 for r in rs if kind(r) == "U"), "added": sum(1 for r in rs if kind(r) == "V"),
                "to_nitro": _stat([_mins(r.get("created_at"), r.get("on_nitro_at")) for r in rs]), "to_attach": _stat([_mins(r.get("created_at"), r.get("attached_at")) for r in att]),
                "nitro_to_attach": _stat([_mins(r.get("on_nitro_at"), r.get("attached_at")) for r in att])}
    by_day, by_show = {}, {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r); by_show.setdefault(r.get("show") or "(no bulletin)", []).append(r)
    slow = sorted(({"name": r.get("name_id"), "show": r.get("show"), "minutes": _mins(r.get("created_at"), r.get("attached_at"))} for r in rows if r["state"] == "ATTACHED" and r.get("attached_at")), key=lambda x: -(x["minutes"] or 0))[:5]
    return {"total": block(rows), "days": [dict(day=d, **block(v)) for d, v in sorted(by_day.items())],
            "shows": sorted(({"show": s, **block(v)} for s, v in by_show.items()), key=lambda x: (-x["late"], -x["clips"])), "slowest": [x for x in slow if x["minutes"] is not None]}


class InsightsMixin:
    def a_bot_checkname(self, r):
        name = (r.q.get("name") or "").strip()
        if len(name) > 200: raise HttpError(400, "That name is too long")
        plan = self.a_bot_story(r)      # same sign-in and view right; it also raises the 400 / 404 for a missing bulletin or story
        if not plan["main"] and not plan["added"] and not plan["next_v"]: raise HttpError(404, "this story has no clip to check against")
        res = check_name({"main": plan["main"], "added": plan["added"], "next_v": plan["next_v"], "next_v_no": plan["next_v_no"]}, plan["base"], name, suffix_on())
        res["base"] = plan["base"]; return res

    def _nitro_file(self, cid):
        with self.db.tx() as cur:
            c = cur.one("SELECT id, display_id, attach_dur FROM clip_ids WHERE id=?", (cid,))
            if not c: raise HttpError(404, "no such clip")
            f = cur.q("SELECT nitro_path FROM files WHERE clip_id=? AND nitro_path IS NOT NULL ORDER BY id DESC", (cid,))
        if not f: raise HttpError(404, "This clip is not on Nitro yet")
        return c, f[0]["nitro_path"]

    def a_quality(self, r):
        c, path = self._nitro_file(int(r.m[0]))
        res = quality.analyse(path, c["attach_dur"])
        with self.db.tx() as cur: self.log(cur, r.user["username"], "quality_check", {"clip": c["display_id"], "verdict": res["verdict"]})      # the only trace: who looked and what it said (no file, no picture)
        return res

    def a_frames(self, r):
        c, path = self._nitro_file(int(r.m[0]))
        ai = (r.q.get("ai") or "0") == "1"
        res = clipsummary.describe(path, ai=ai)
        if ai:
            with self.db.tx() as cur: self.log(cur, r.user["username"], "clip_ai_summary", {"clip": c["display_id"], "ok": "summary" in res})
        return res

    def a_standards(self, r):
        """v10.16.0: the AI standards check (violence, sexual content, distress NOT blurred). Only while an admin has switched it on; frames go to Groq; nothing is stored, one event line says who ran it and the counts."""
        self.feat_need("standards_ai")
        if not standards.available(): raise HttpError(503, "The AI standards check needs GROQ_API_KEY in autoid.env (it is empty)")
        c, path = self._nitro_file(int(r.m[0])); res = standards.check(path)
        with self.db.tx() as cur: self.log(cur, r.user["username"], "standards_check", {"clip": c["display_id"], "frames": res["counts"]["frames"], "visible": res["counts"]["visible"], "blurred": res["counts"]["blurred"], "unchecked": res["counts"]["unchecked"], "ai_error": bool(res.get("ai_error"))})
        return res

    def a_scan_asset(self, r): return scanassets.read(r.m[0])      # v10.13.0: the browser scan's model files, for a signed-in page

    def a_analytics(self, r):
        try: days = min(31, max(1, int(r.q.get("days") or 7)))
        except ValueError: raise HttpError(400, "days must be a whole number from 1 to 31")
        end = self.today(); start = end - dt.timedelta(days=days - 1)
        with self.db.tx() as cur:
            rows = cur.q("""SELECT c.day, c.version, c.state, c.created_at, c.on_nitro_at, c.attached_at, COALESCE(c.name_id, c.display_id) AS name_id, ru.name AS show, ru.start_at
                            FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id
                            WHERE c.day>=? AND c.day<=? AND s.deleted=0 AND c.replaced_at IS NULL""", (start.isoformat(), end.isoformat()))
        out = summarise(rows); out.update({"from": start.isoformat(), "to": end.isoformat(), "days_asked": days}); return out
