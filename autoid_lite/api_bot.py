"""v10.11.0 Editor chatbot (the floating chat button on every page).

The bot only READS. It never sends anything to Blaze and never creates anything: it looks at the clip IDs the registry already holds for a story and tells the editor the EXACT file name to export,
by the Clip Naming Rule Book:
  * Append  = one more clip next to the ones already there  -> DDMMYY_SLUG_V01, then _V02 ...      (the next number of its kind, never skipped)
  * Update  = replace a clip that is already there           -> main clip: _U01, _U02 ...;  an added clip: _V01_U01, _V01_U02 ...
The file is then picked up by the normal watcher / poller (VERSION_SUFFIX=on), exactly as if the editor had typed the name.
Independent of Quick Support: it has its own read-only calls and works even when SUPPORT_MENU=0."""
from __future__ import annotations
import re
from .common import HttpError
from .api_blazeclips import merge_blaze
from .ids import label_of, norm_name, strip_label, suffix_on

STRIP_RE = re.compile(r"(?:_[UV]\d+)+$", re.I)          # 111126_FIRE_V01_U02 -> 111126_FIRE
MAXN = 99                                                # the rule book: two digits


def base_of(name): return STRIP_RE.sub("", strip_label(name))


def plan_names(base, rows):
    """Pure function (tested on its own). rows: the clip IDs of ONE story name, each {version, state, replaced_at, name_id}.
    -> {"main": slot, "added": [slot, ...], "next_v": name or None}; a slot = {key, label, current, state, in_story, next_u, next_u_name}.
    Stored versions: 1 plain clip, 1000+n _Un, 2000+n _Vn, 10000 + V*100 + U for _Vv_Uu (an update OF an added clip)."""
    byv = {}
    for x in rows:                                       # the same version can be in several bulletins: the one that is really in the story wins
        v = int(x["version"] or 1); old = byv.get(v)
        if old is None or (x["state"] == "ATTACHED" and not x.get("replaced_at") and not (old["state"] == "ATTACHED" and not old.get("replaced_at"))): byv[v] = x
    main = sorted(v for v in byv if v == 1 or 1000 < v < 2000)
    vs = sorted({v - 2000 for v in byv if 2000 < v < 3000} | {(v - 10000) // 100 for v in byv if 10000 <= v < 20000})

    def slot(key, label, versions, name_for):
        cur = max(versions) if versions else None
        row = byv.get(cur) if cur is not None else None
        n_u = max([(v % 1000 if key == "main" else v % 100) for v in versions if (v > 1000 and key == "main") or (v >= 10000 and key != "main")] or [0])
        nxt = n_u + 1
        return {"key": key, "label": label, "current": row["name_id"] if row else None, "state": row["state"] if row else None,
                "in_story": bool(row and row["state"] == "ATTACHED" and not row.get("replaced_at")), "update_no": n_u,
                "next_u": nxt if nxt <= MAXN else None, "next_u_name": name_for(nxt) if nxt <= MAXN else None}
    m = slot("main", "Main clip", main, lambda n: "%s_U%02d" % (base, n)) if main else None
    added = []
    for n in vs:
        vers = [v for v in byv if v == 2000 + n or (10000 <= v < 20000 and (v - 10000) // 100 == n)]
        s = slot("V%02d" % n, "Added clip V%02d" % n, vers, lambda u, n=n: "%s_V%02d_U%02d" % (base, n, u)); added.append(s)
    nv = (vs[-1] if vs else 0) + 1
    return {"main": m, "added": added, "next_v": "%s_V%02d" % (base, nv) if nv <= MAXN else None, "next_v_no": nv if nv <= MAXN else None}


def _stem(name): return re.sub(r"\.[A-Za-z0-9]{2,4}$", "", re.split(r"[\\/]", (name or "").strip())[-1])


def clip_labels(rows, bclips, files):
    """v11.2.0, pure (tested on its own). The label each clip carries in its file name: 111126_FIRE_V01 (byte), 111126_FIRE (tag) ... -> {norm_name(clip name): 'byte' | 'minibyte' | 'tag' | 'del' | the text in brackets}.
    The label is only ever in the file name as the editor typed it, never in the registry, so it is read back from the two places that still hold that name: the file names the watcher saw
    (files: [{clip_id, name}], oldest first) and Blaze's own clip titles (bclips: [{title}]; what is really in the story, so it has the last word: a clip that Blaze holds WITHOUT a label shows none).
    A clip with no label simply has no entry. Nothing is guessed and nothing is stored. With VERSION_SUFFIX=off the labels are not read at all (the matching ignores them too)."""
    out = {}
    if not suffix_on(): return out
    seen = {}
    for f in files or []:
        lab = label_of(_stem(f.get("name")))
        if lab: seen[f.get("clip_id")] = lab
    for x in rows or []:
        k = norm_name(x.get("name_id") or x.get("display_id") or ""); lab = x.get("label") or seen.get(x.get("id"))
        if k and lab: out[k] = lab
    for c in bclips or []:
        raw = _stem(c.get("title")); clean = strip_label(raw); k = norm_name(clean)
        if not k: continue
        lab = label_of(raw) if clean != raw else ""
        if lab: out[k] = lab
        else: out.pop(k, None)
    return out


class BotMixin:
    def a_bot_bulletins(self, r):
        """The bulletins of a day that have stories with clip IDs (the first step of the chat). ?day=YYYYMMDD, default: the broadcast day."""
        d = (r.q.get("day") or "").strip()
        try: day = (__import__("datetime").datetime.strptime(d, "%Y%m%d").date() if re.fullmatch(r"\d{8}", d) else self.today()).isoformat()
        except ValueError: raise HttpError(400, "day must be a real date written YYYYMMDD")
        with self.db.tx() as cur:
            rows = cur.q("""SELECT ru.blaze_rundown_id AS id, ru.name, ru.start_at, COUNT(DISTINCT s.id) AS stories FROM rundowns ru JOIN stories s ON s.rundown_id=ru.id JOIN clip_ids c ON c.story_id=s.id
                            WHERE c.day=? AND s.deleted=0 AND ru.blaze_rundown_id NOT LIKE 'name:%' AND s.blaze_story_id NOT LIKE 'manual-%'
                            GROUP BY ru.id ORDER BY COALESCE(ru.start_at,''), ru.name""", (day,))
        for x in rows: x["aired"] = self.aired(x["start_at"])
        return {"day": day, "bulletins": rows}

    def a_bot_stories(self, r):
        rid = (r.q.get("rundown") or "").strip()
        if not rid: raise HttpError(400, "choose the bulletin first")
        with self.db.tx() as cur:
            ru = cur.one("SELECT start_at FROM rundowns WHERE blaze_rundown_id=?", (rid,))
            if not ru: raise HttpError(404, "unknown bulletin")
            rows = cur.q("""SELECT s.blaze_story_id AS id, COALESCE(NULLIF(TRIM(s.slug),''), NULLIF(TRIM(s.story_title),''), 'story ' || s.blaze_story_id) AS title, s.position AS pos
                            FROM stories s JOIN rundowns ru ON ru.id=s.rundown_id WHERE ru.blaze_rundown_id=? AND s.deleted=0 AND s.blaze_story_id NOT LIKE 'manual-%'
                              AND EXISTS (SELECT 1 FROM clip_ids c WHERE c.story_id=s.id)
                            ORDER BY s.position IS NULL, s.position, s.id""", (rid,))
        return {"stories": rows, "aired": self.aired(ru["start_at"])}

    def a_bot_story(self, r):
        """What is in this story and what the next file names are. ?rundown=<show id>&story=<Blaze story id>"""
        rid, sid = (r.q.get("rundown") or "").strip(), (r.q.get("story") or "").strip()
        if not rid or not sid: raise HttpError(400, "choose the bulletin and the story")
        with self.db.tx() as cur:
            st = cur.one("""SELECT s.id, s.blaze_story_id, s.slug, s.story_title, ru.name AS rundown, ru.start_at FROM stories s JOIN rundowns ru ON ru.id=s.rundown_id
                            WHERE ru.blaze_rundown_id=? AND s.blaze_story_id=? AND s.deleted=0""", (rid, sid))
            if not st: raise HttpError(404, "unknown story")
            mine = cur.q("SELECT c.id, c.day, c.name_id, c.display_id, c.version, c.state, c.replaced_at FROM clip_ids c WHERE c.story_id=? ORDER BY c.id", (st["id"],))
            if not mine: raise HttpError(404, "this story has no clip ID yet, so there is no name to build on")
            day = max(x["day"] for x in mine)
            plain = next((x for x in mine if int(x["version"] or 1) == 1), None)
            base = base_of((plain or mine[0])["name_id"] or (plain or mine[0])["display_id"])
            allr = cur.q("""SELECT c.id, c.name_id, c.display_id, c.version, c.state, c.replaced_at, s.blaze_story_id FROM clip_ids c JOIN stories s ON s.id=c.story_id WHERE c.day=? AND s.deleted=0""", (day,))
            same = [x for x in allr if x["blaze_story_id"] == sid or norm_name(base_of(x["name_id"] or x["display_id"])) == norm_name(base)]      # the same story in other bulletins, and stories with the same name: one clip name
            bul = cur.q("""SELECT DISTINCT ru.name, ru.start_at FROM stories s JOIN rundowns ru ON ru.id=s.rundown_id WHERE s.blaze_story_id=? AND s.deleted=0 ORDER BY COALESCE(ru.start_at,''), ru.name""", (sid,))
        for x in same: x["name_id"] = x["name_id"] or x["display_id"]
        bclips, how, seen, note = self.blaze_clips_now(r, rid, sid)                      # v10.17.0: the REAL clip list from Blaze (the read-only request the Delete button uses), merged with the registry
        same, others = merge_blaze(base, same, bclips) if how != "none" else (same, [])
        plan = plan_names(base, same)
        files = []                                                                       # v11.2.0: the file names the watcher saw for these clips (they still carry the (byte) / (minibyte) / (tag) / (del) label the editor typed)
        ids = [x["id"] for x in same if x.get("id")]
        if ids and suffix_on():
            with self.db.tx() as cur:
                for i in range(0, len(ids), 400):
                    part = ids[i:i + 400]
                    files += [{"clip_id": f["clip_id"], "name": f["p"]} for f in cur.q("SELECT clip_id, COALESCE(nas_path, nitro_path) AS p FROM files WHERE clip_id IN (%s) AND (nas_path IS NOT NULL OR nitro_path IS NOT NULL) ORDER BY id" % ",".join("?" * len(part)), part)]
        labels = clip_labels(same, bclips if how != "none" else [], files)
        for sl in ([plan["main"]] if plan["main"] else []) + plan["added"]: sl["current_label"] = labels.get(norm_name(sl["current"] or ""), "")
        clips = sorted(({"name": x["name_id"], "version": int(x["version"] or 1), "state": x["state"], "replaced": bool(x.get("replaced_at")), "label": labels.get(norm_name(x["name_id"]), "")} for x in {int(y["version"] or 1): y for y in same}.values()), key=lambda y: (y["version"] != 1, y["version"] >= 10000, y["version"]))
        return {"story": {"id": sid, "title": (st["slug"] or st["story_title"] or "").strip() or "story " + sid, "bulletin": st["rundown"], "aired": self.aired(st["start_at"])},
                "base": base, "day": day, "clips": clips, "main": plan["main"], "added": plan["added"], "next_v": plan["next_v"], "next_v_no": plan["next_v_no"],
                "bulletins": [{"name": b["name"], "aired": self.aired(b["start_at"])} for b in bul], "version_suffix": suffix_on(),
                "blaze": {"source": how, "seen_at": seen, "note": note, "count": len(bclips)}, "other_clips": others}
