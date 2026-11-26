"""Server methods for the dashboard: clip list, rundowns, versions, history, events, CSV export, report page."""
from __future__ import annotations
from pathlib import Path
import csv, datetime as dt, io, json, os, re, time, uuid
from .config import data_dir
from .ids import kind_of, name_base, suffix_on, vlabel
from .db import now_iso
from .common import HttpError, norm
from . import preview

class DashboardMixin:
    @staticmethod
    def user_cond(user):
        """v10.9.0: the username filter. A story matches when its creator OR the user it is assigned to is the Blaze username (any letter case).
        v10.9.0: several usernames, comma separated (venkat,abarna): a story matches when ANY of them created it or is assigned to it. At most 60 names. -> (sql, args) or (None, [])."""
        names = list(dict.fromkeys(u.strip().lower()[:80] for u in (user or "").split(",") if u.strip()))[:60]
        if not names: return None, []
        m = ",".join("?" * len(names))
        return "(LOWER(COALESCE(s.created_by,'')) IN (%s) OR LOWER(COALESCE(s.assigned_to,'')) IN (%s))" % (m, m), names + names
    @staticmethod
    def editor_cond(editor):
        """v10.9.5: the editor-name filter. The editors write their name in the slug's comment in Blaze (stories.editor); a story matches when that text equals one of the given names (any letter case).
        Several names, comma separated, at most 60. -> (sql, args) or (None, [])."""
        names = list(dict.fromkeys(u.strip().lower()[:120] for u in (editor or "").split(",") if u.strip()))[:60]
        none = "__none__" in names; names = [n for n in names if n != "__none__"]               # v10.20.0: the token __none__ means "unassigned": the story carries no editor name
        if not names and not none: return None, []
        parts, args = [], []
        if names: parts.append("LOWER(COALESCE(s.editor,'')) IN (%s)" % ",".join("?" * len(names))); args += names
        if none: parts.append("TRIM(COALESCE(s.editor,''))=''")
        return (parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"), args
    @staticmethod
    def created_cond(created):
        """v10.20.0: the Created-by filter. A story matches when the Blaze username that created it equals one of the given names (any letter case). Several names, comma separated, at most 60. -> (sql, args) or (None, [])."""
        names = list(dict.fromkeys(u.strip().lower()[:80] for u in (created or "").split(",") if u.strip()))[:60]
        if not names: return None, []
        return "LOWER(COALESCE(s.created_by,'')) IN (%s)" % ",".join("?" * len(names)), names
    @staticmethod
    def day_editors(cur, day, extra="", args=()):
        """v10.9.5: every editor name (slug comment) that a story of the day carries: [{name, n}] for the drop-down."""
        out = {}
        for x in cur.q("SELECT s.editor AS name, COUNT(DISTINCT s.id) AS n FROM clip_ids c JOIN stories s ON s.id=c.story_id WHERE c.day=? AND s.editor IS NOT NULL AND s.editor<>'' %s GROUP BY LOWER(s.editor)" % extra, [day] + list(args)):
            out[x["name"].lower()] = {"name": x["name"], "n": x["n"]}
        return sorted(out.values(), key=lambda o: o["name"].lower())
    @staticmethod
    def day_users(cur, day, extra="", args=()):
        """v10.9.0: every username that created or was assigned a story of the day: [{name, created, assigned, n}] for the drop-down. `extra` is an additional AND condition (feed: only clips with a file)."""
        out = {}
        for col, key in (("created_by", "created"), ("assigned_to", "assigned")):
            for x in cur.q("SELECT s.%s AS name, COUNT(DISTINCT s.id) AS n FROM clip_ids c JOIN stories s ON s.id=c.story_id WHERE c.day=? AND s.%s IS NOT NULL AND s.%s<>'' %s GROUP BY LOWER(s.%s)" % (col, col, col, extra, col), [day] + list(args)):
                o = out.setdefault(x["name"].lower(), {"name": x["name"], "created": 0, "assigned": 0}); o[key] = x["n"]
        return sorted(({**o, "n": o["created"] + o["assigned"]} for o in out.values()), key=lambda o: o["name"].lower())
    def a_status(self, r): return {"problems": [m for _, (ok, m) in self.compute_health().items() if not ok]}
    def a_clips(self, r):
        """The day's clip IDs. Without page parameters: all of them (as before). With per_page (1 to 200), page, filter (all, action, nitro, attention, waiting, done), show (Blaze show id) and q: one page of the matching clips,
        plus the counts for the whole day, so a 700-story day can be browsed. q: every word must match somewhere in the slug title, the story name, the clip ID, the Blaze story ID, the slug ID, the show ID, the bulletin name or the
        bulletin time (14:30 or 1430, in the server's local time). Order when paging: needing action first, then show, then row.
        v10.9.4: filter `removed` (stories struck out because Blaze no longer lists them); hide_removed=1 leaves out the struck-out stories that need nothing from the desk (one still on Nitro or held stays, it needs the desk); sort=row|title|status with dir=asc|desc replaces the default order (the bulletins keep their order, the rows inside them follow the sort; status: needs the desk first). `shows`: every show of the day; `bulletins`: the shows that still have matching stories, with their counts."""
        d = dt.datetime.strptime(r.q["day"], "%Y%m%d").date() if r.q.get("day") else self.today(); q = r.q
        try: per = int(q["per_page"]) if q.get("per_page") else 0; page = max(1, int(q.get("page") or 1))
        except ValueError: raise HttpError(400, "page and per_page must be numbers")
        per = max(0, min(per, 200)); flt = (q.get("filter") or "all").lower()
        if flt not in ("all", "action", "nitro", "attention", "waiting", "done", "removed"): raise HttpError(400, "filter must be all, action, nitro, attention, waiting, done or removed")
        srt, dirn = (q.get("sort") or "").lower(), (q.get("dir") or "asc").lower()
        if srt not in ("", "row", "title", "status", "clips"): raise HttpError(400, "sort must be row, title, status or clips")
        if dirn not in ("asc", "desc"): raise HttpError(400, "dir must be asc or desc")
        hide = (q.get("hide_removed") or "").lower() in ("1", "true", "yes") and flt != "removed"
        ACT, DONE, NITRO, ATTN = ("ON_NITRO", "NEEDS_DESK", "ATTACH_SUBMITTED", "QUARANTINED"), ("ATTACHED",), ("ON_NITRO",), ("NEEDS_DESK", "QUARANTINED")
        marks = lambda t: ",".join("?" * len(t))
        where, args = ["c.day=?"], [d.isoformat()]
        for w in (q.get("q") or "").lower().split()[:8]:
            like = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            cols = ("LOWER(s.slug)", "LOWER(COALESCE(s.story_title,''))", "LOWER(c.display_id)", "LOWER(COALESCE(c.name_id,''))", "COALESCE(c.media_id,'')", "COALESCE(c.item_id,'')", "s.blaze_story_id", "COALESCE(s.slug_id,'')", "ru.blaze_rundown_id", "LOWER(COALESCE(ru.name,''))",
                    "COALESCE(strftime('%H:%M', ru.start_at, 'localtime'),'')", "COALESCE(strftime('%H%M', ru.start_at, 'localtime'),'')", "LOWER(COALESCE(s.created_by,''))", "LOWER(COALESCE(s.assigned_to,''))", "LOWER(COALESCE(s.editor,''))")
            where.append("(" + " OR ".join("%s LIKE ? ESCAPE '\\'" % c for c in cols) + ")"); args += [like] * len(cols)
        uc, ua = self.user_cond(q.get("user"))                                                          # v10.9.0: username filter (creator or assigned-to); it also narrows the bulletin list and its counts
        if uc: where.append(uc); args += ua
        ec, ea = self.editor_cond(q.get("editor"))                                                       # v10.9.5: editor-name filter (the slug comment); it also narrows the bulletin list and its counts
        if ec: where.append(ec); args += ea
        cc, ca = self.created_cond(q.get("created"))                                                     # v10.20.0: created-by filter (several names)
        if cc: where.append(cc); args += ca
        nh_where, nh_args = list(where), list(args)                                                      # v10.9.4: the same without "hide removed", for the count of removed stories
        if hide: where.append("NOT (COALESCE(s.deleted,0)=1 AND c.state NOT IN ('ON_NITRO','NEEDS_DESK','ATTACH_SUBMITTED','QUARANTINED'))")
        tbl = "FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id WHERE "
        qbase = tbl + " AND ".join(where); sbase = qbase; sargs = list(args)                       # q applied, no show restriction (the bulletin list)
        if (q.get("show") or "").strip(): where.append("ru.blaze_rundown_id=?"); args.append(q["show"].strip()); nh_where.append("ru.blaze_rundown_id=?"); nh_args.append(q["show"].strip())
        base = tbl + " AND ".join(where); rbase = tbl + " AND ".join(nh_where)
        stwhere = {"all": "", "action": " AND c.state IN (%s)" % marks(ACT), "nitro": " AND c.state IN (%s)" % marks(NITRO), "attention": " AND c.state IN (%s)" % marks(ATTN),
                   "done": " AND c.state IN (%s)" % marks(DONE), "waiting": " AND c.state NOT IN (%s)" % marks(ACT + DONE), "removed": " AND COALESCE(s.deleted,0)=1"}[flt]
        stargs = {"all": [], "action": list(ACT), "nitro": list(NITRO), "attention": list(ATTN), "done": list(DONE), "waiting": list(ACT + DONE), "removed": []}[flt]
        inflt = lambda st: (flt == "all" or (flt == "action" and st in ACT) or (flt == "nitro" and st in NITRO) or (flt == "attention" and st in ATTN) or (flt == "done" and st in DONE) or (flt == "waiting" and st not in ACT + DONE))
        D, rid = ("DESC" if dirn == "desc" else "ASC"), "CAST(ru.blaze_rundown_id AS INTEGER)"
        rank = "CASE c.state WHEN 'NEEDS_DESK' THEN 0 WHEN 'QUARANTINED' THEN 1 WHEN 'ON_NITRO' THEN 2 WHEN 'ATTACH_SUBMITTED' THEN 3 WHEN 'VERIFIED' THEN 4 WHEN 'EXPORTING' THEN 5 WHEN 'WAITING_FOR_CLIP' THEN 6 WHEN 'ATTACHED' THEN 7 ELSE 8 END"
        pos = "s.position IS NULL, s.position"
        order = {"row": "ORDER BY %s, s.position IS NULL, s.position %s, c.seq, c.id" % (rid, D),
                 "title": "ORDER BY LOWER(COALESCE(NULLIF(s.story_title,''), NULLIF(s.slug,''), c.display_id)) %s, %s, %s, c.seq, c.id" % (D, rid, pos),
                 "status": "ORDER BY %s %s, %s, %s, c.seq, c.id" % (rank, D, rid, pos),
                 "clips": "ORDER BY (SELECT COUNT(*) FROM clip_ids c2 WHERE c2.story_id=c.story_id AND c2.state='ATTACHED' AND c2.replaced_at IS NULL) %s, %s, %s, c.seq, c.id" % (D, rid, pos)}.get(srt) or (("ORDER BY CASE WHEN c.state IN ('ON_NITRO','NEEDS_DESK','ATTACH_SUBMITTED') THEN 0 ELSE 1 END, CAST(ru.blaze_rundown_id AS INTEGER), s.position IS NULL, s.position, c.seq, c.id") if per else "ORDER BY c.seq, c.id")
        with self.db.tx() as cur:
            by = {x["state"]: x["n"] for x in cur.q("SELECT c.state, COUNT(*) AS n " + base + " GROUP BY c.state", args)}
            shows = cur.q("SELECT ru.blaze_rundown_id AS id, ru.name, ru.start_at AS start, COUNT(*) AS n FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id WHERE c.day=? GROUP BY ru.id ORDER BY ru.start_at IS NULL, datetime(ru.start_at), CAST(ru.blaze_rundown_id AS INTEGER), ru.name", (d.isoformat(),))
            bul = {}
            removed_n = cur.one("SELECT COUNT(*) AS n " + rbase + " AND COALESCE(s.deleted,0)=1", nh_args)["n"]
            for x in cur.q("SELECT ru.blaze_rundown_id AS id, c.state AS st, COUNT(*) AS n, SUM(COALESCE(s.deleted,0)) AS d " + sbase + " GROUP BY ru.id, c.state", sargs):
                b = bul.setdefault(x["id"], {"m": 0, "nitro": 0, "attn": 0, "wait": 0, "done": 0, "n": 0, "d": 0}); b["n"] += x["n"]; b["d"] += x["d"] or 0
                if inflt(x["st"]): b["m"] += x["n"]
                if x["st"] in NITRO: b["nitro"] += x["n"]
                elif x["st"] in ATTN: b["attn"] += x["n"]
                elif x["st"] in DONE: b["done"] += x["n"]
                elif x["st"] not in ACT: b["wait"] += x["n"]
            if flt == "removed":
                for b in bul.values(): b["m"] = b["d"]
            total = removed_n if flt == "removed" else sum(n for st, n in by.items() if inflt(st))
            pages = max(1, -(-total // per)) if per else 1; page = min(page, pages)
            rows = cur.q("""SELECT c.id, c.display_id, COALESCE(c.name_id, c.display_id) AS name_id, c.media_id AS mos_object_id, c.item_id, c.attach_dur, c.blaze_clip_id, c.qa_state, c.qa_by, c.qa_at, c.qa_msg, c.version, c.story_id, c.replaced_at, c.replaced_by, c.state, s.slug, s.story_title, SUBSTR(s.online_script, 1, 400) AS online_script, SUBSTR(s.anchor_script, 1, 400) AS anchor_script, LENGTH(s.online_script) AS online_len, LENGTH(s.anchor_script) AS anchor_len, s.script_at, s.deleted, s.deleted_reason, s.created_by, s.assigned_to, s.editor, ru.name AS rundown, ru.start_at AS show_start, ru.blaze_rundown_id, s.blaze_story_id, s.slug_id, s.position, c.created_at,
                COALESCE(c.attach_error, (SELECT error FROM files f WHERE f.clip_id=c.id ORDER BY f.id DESC LIMIT 1)) AS error,
                (SELECT nas_path FROM files f WHERE f.clip_id=c.id AND f.nas_path IS NOT NULL ORDER BY f.id LIMIT 1) AS _nas, (SELECT nitro_path FROM files f WHERE f.clip_id=c.id AND f.nitro_path IS NOT NULL ORDER BY f.id DESC LIMIT 1) AS _nit,
                c.on_nitro_at AS _onair_at, c.media_found_at AS _media_at, c.attached_at AS _att_at """ + base + stwhere + " " + order + (" LIMIT %d OFFSET %d" % (per, (page - 1) * per) if per else ""), args + stargs)
        for x in rows: x["stages"] = self.stages(x)
        hand = {}
        if rows:                                                                          # v10.18.0: the count of clips Blaze holds that Storigen did not make is worked out for every setting (it used to need VERSION_SUFFIX=on, so a clip added with + showed nowhere on the story card when it was off)
            with self.db.tx() as cur: hand = self.hand_counts(cur, rows)
            for x in rows: x["hand_clips"] = hand.get(x["story_id"], 0)
        if rows:                                                                          # v10.5.0: the story's clips for the badge. v10.7.0: story_clips = the clips really in the story (attached and not replaced), not the number of clip IDs; replaced_label = which update took a clip's place. v11.2.0: story_clips is worked out whatever VERSION_SUFFIX is, so a story whose clip is not attached yet says 0, not 1
            with self.db.tx() as cur:
                ids = sorted({x["story_id"] for x in rows}); info = {}
                for i in range(0, len(ids), 500):
                    part = ids[i:i + 500]
                    for y in cur.q("SELECT story_id, SUM(CASE WHEN state='ATTACHED' AND replaced_at IS NULL THEN 1 ELSE 0 END) AS n, MAX(CASE WHEN version>1000 AND version<2000 THEN version END) AS u FROM clip_ids WHERE story_id IN (%s) GROUP BY story_id" % ",".join("?" * len(part)), part): info[y["story_id"]] = y
            for x in rows:
                y = info.get(x["story_id"]) or {}; x["story_clips"] = (y.get("n") or 0) + hand.get(x["story_id"], 0)
                if suffix_on(): x["replaced_label"] = (re.search(r"_([UV]\d+)$", x["replaced_by"]).group(1) if x.get("replaced_by") and re.search(r"_([UV]\d+)$", x["replaced_by"]) else None); x["story_update"] = vlabel(y["u"]) if y.get("u") else None; x["vlabel"] = vlabel(x["version"]) if kind_of(x["version"]) else None
        wmap, wts = getattr(self, "why", ({}, 0)); wlive = time.time() - wts < 120          # v9.13.1: only while the poller is sending it
        for x in rows: x["why"] = wmap.get(x["display_id"]) if wlive and x["state"] != "ATTACHED" else None
        for x in rows: x["deleted"] = bool(x["deleted"]); x["typed"] = x["blaze_rundown_id"].startswith("name:") or x["blaze_story_id"].startswith("manual-")
        bulletins = [dict(sh, **bul[sh["id"]]) for sh in shows if sh["id"] in bul and bul[sh["id"]]["m"]]
        n = lambda *st: sum(by.get(x, 0) for x in st)
        counts = {"all": sum(by.values()), "action": n(*ACT), "done": n(*DONE), "waiting": sum(by.values()) - n(*ACT) - n(*DONE), "on_nitro": n("ON_NITRO"), "needs_desk": n("NEEDS_DESK", "QUARANTINED"), "attached": n("ATTACHED"), "removed": removed_n}
        with self.db.tx() as cur:
            dby = {x["state"]: x["n"] for x in cur.q("SELECT state, COUNT(*) AS n FROM clip_ids WHERE day=? GROUP BY state", (d.isoformat(),))}
            users = self.day_users(cur, d.isoformat()); editors = self.day_editors(cur, d.isoformat())
        dn = lambda *st: sum(dby.get(x, 0) for x in st)
        day_counts = {"all": sum(dby.values()), "action": dn(*ACT), "done": dn(*DONE), "waiting": sum(dby.values()) - dn(*ACT) - dn(*DONE), "on_nitro": dn("ON_NITRO"), "needs_desk": dn("NEEDS_DESK", "QUARANTINED"), "attached": dn("ATTACHED")}   # the whole day, whatever the search, filter or show: the cards at the top
        return {"day": d.isoformat(), "clips": rows, "total": total, "page": page, "pages": pages, "per_page": per, "counts": counts, "day_counts": day_counts, "shows": shows, "bulletins": bulletins, "users": users, "editors": editors}
    def stages(self, x):
        """The four-step strip of one story: EXPORT (the inbox folder the file was seen in) -> ON AIR (the file moved to the on-air folder) -> NITRO (Blaze's media object, its mosObjectId, was found) -> ATTACHED. Facts only: each is true only when it was recorded."""
        nas, nit = x.pop("_nas", None), x.pop("_nit", None); onair_at, media_at, att_at = x.pop("_onair_at", None), x.pop("_media_at", None), x.pop("_att_at", None)
        att = x["state"] == "ATTACHED" or bool(att_at); folder = None
        if nas:
            parts = [p for p in re.split(r"[\\/]", nas) if p]; parent = parts[-2] if len(parts) >= 2 else ""
            root = [p for p in re.split(r"[\\/]", os.environ.get("EXPORTS_DIR") or "") if p]
            folder = parent if parent and parent.upper() != (root[-1].upper() if root else "") else None
        onair = bool(onair_at or nit or x["state"] in ("ON_NITRO", "ATTACH_SUBMITTED"))
        return {"export": bool(nas), "export_folder": folder, "onair": onair or att, "nitro": bool(media_at) or att, "attached": att}
    def a_rundowns(self, r):
        since = (self.today() - dt.timedelta(days=3)).isoformat()
        with self.db.tx() as cur:
            return [x["name"] for x in cur.q("""SELECT DISTINCT ru.name FROM rundowns ru JOIN stories s ON s.rundown_id=ru.id JOIN clip_ids c ON c.story_id=s.id
                                               WHERE c.day>=? AND ru.name IS NOT NULL ORDER BY ru.name""", (since,))]
    def a_manual(self, r):
        """Placeholder mode: the journalist types the rundown name and the story name exactly as shown in Blaze and gets the ID."""
        if not self.manual_enabled(): raise HttpError(409, "Typing IDs is switched off (LINK_MODE=story_id): the ID is made when Blaze reports the story. Ask the admin if it does not appear.")
        b = r.body; story = (b.get("story") or b.get("slug") or "").strip(); rundown = (b.get("rundown") or "").strip()
        if not story: raise HttpError(400, "enter the story name")
        if self.cfg["link_mode"] == "placeholder" and not rundown: raise HttpError(400, "enter the rundown name")
        rname = rundown or "MANUAL"
        with self.db.tx() as cur:
            day = self.today(); key = "name:" + norm(rname)
            if not b.get("confirm_duplicate"):
                for x in cur.q("""SELECT s.slug, c.display_id FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id
                                  WHERE ru.blaze_rundown_id=? AND s.deleted=0 AND c.day=? AND c.version=1""", (key, day.isoformat())):
                    if norm(x["slug"]) == norm(story):
                        raise HttpError(409, "'%s' in rundown '%s' already has ID %s today. Create another ID only if this is a different story." % (story, rname, x["display_id"]), duplicate=x["display_id"])
            rid = self.get_rundown(cur, key, rname)
            sid = cur.insert("INSERT INTO stories(blaze_story_id,rundown_id,slug,last_seen_at) VALUES(?,?,?,?)", ("manual-" + uuid.uuid4().hex, rid, story, now_iso()))
            clip = self.new_clip(cur, sid, story, day, self.next_seq(cur, day))
            self.log(cur, r.user["username"], "manual_clip_id", {"display_id": clip["display_id"], "rundown": rname, "story": story})
            clip["rundown"], clip["story"] = rname, story; return clip
    def scope_of(self, cur, cid):
        """The stories that share this clip's name today, with each story's LATEST version. -> (clicked row, [rows of that name, newest version per story, in show order])
        'later' = the clicked story and every story of a show that starts at or after the clicked show, still at the clicked version (earlier, aired shows keep what they have)."""
        c = cur.one("""SELECT c.*, COALESCE(c.name_id, c.display_id) AS nm, s.slug, ru.start_at, ru.name AS rundown FROM clip_ids c JOIN stories s ON s.id=c.story_id
                       JOIN rundowns ru ON ru.id=s.rundown_id WHERE c.id=?""", (cid,))
        if not c: raise HttpError(404, "no such clip")
        base = name_base(c["nm"]).upper().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = [x for x in cur.q("""SELECT c.id, c.display_id, COALESCE(c.name_id, c.display_id) AS nm, c.version, c.state, c.story_id, c.seq, c.day, s.slug, s.deleted, s.blaze_story_id,
                                   ru.name AS rundown, ru.start_at, (SELECT COUNT(*) FROM files f WHERE f.clip_id=c.id) AS nfiles
                                   FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id
                                   WHERE c.day=? AND UPPER(COALESCE(c.name_id, c.display_id)) LIKE ? ESCAPE '\\'""", (c["day"], base + "%"))
                if name_base(x["nm"]).upper() == name_base(c["nm"]).upper()]
        latest = {}
        for x in rows:
            if x["story_id"] not in latest or x["version"] > latest[x["story_id"]]["version"]: latest[x["story_id"]] = x
        mine = latest[c["story_id"]]
        return c, mine, sorted(latest.values(), key=lambda x: (x["start_at"] or "", x["rundown"] or "", x["id"])), rows
    def scope_targets(self, c, mine, latest, scope):
        if scope == "this" or c["name_id"] is None: return [mine]
        key = lambda x: x["start_at"] or ""
        return [x for x in latest if x["version"] == mine["version"] and not x["deleted"] and (x["story_id"] == mine["story_id"] or (key(x) >= key(mine) and (key(mine) or x["rundown"] == mine["rundown"])))]
    def a_scope(self, r):
        """What '+ Version' / 'Delete version' would touch: this story only, or this show and the later shows that hold the same story name."""
        with self.db.tx() as cur:
            c, mine, latest, rows = self.scope_of(cur, int(r.m[0])); later = self.scope_targets(c, mine, latest, "later")
        show = lambda x: {"id": x["id"], "rundown": x["rundown"], "start": x["start_at"], "state": x["state"], "version": x["version"], "name_id": x["nm"]}
        return {"name_id": mine["nm"], "version": mine["version"], "new_version": max(x["version"] for x in rows) + 1, "shared": c["name_id"] is not None and len(latest) > 1,
                "this": [show(mine)], "later": [show(x) for x in later], "all": len(latest)}
    def a_version(self, r):
        """New version of a clip. scope=this (default): only this story. scope=later: this story and the same-named stories of the later shows (the earlier, aired shows keep the old clip)."""
        scope = (r.body or {}).get("scope") or "this"
        if scope not in ("this", "later"): raise HttpError(400, "scope must be this or later")
        if suffix_on(): raise HttpError(409, "VERSION_SUFFIX=on: a new version is made by the file name (NAME_U01.mxf replaces, NAME_V01.mxf is added); there is no +Version button")
        with self.db.tx() as cur:
            c, mine, latest, rows = self.scope_of(cur, int(r.m[0])); targets = self.scope_targets(c, mine, latest, scope)
            n = max(x["version"] for x in rows) + 1; base = name_base(c["nm"]); made = []
            if c["name_id"] is None: n = cur.one("SELECT max(version) AS v FROM clip_ids WHERE story_id=?", (c["story_id"],))["v"] + 1      # a clip from before shared names: as it always was
            for x in targets:
                made.append(self.new_clip(cur, x["story_id"], x["slug"], dt.date.fromisoformat(x["day"]), x["seq"], n, name=None if c["name_id"] is None else "%s_V%d" % (base, n)))
            clip = made[0]; self.log(cur, r.user["username"], "version_added", {"display_id": clip["display_id"], "name_id": clip["name_id"], "scope": scope, "stories": len(made)})
            return dict(clip, created=len(made), scope=scope)
    def a_delete_version(self, r):
        """Undo an accidental '+ Version'. Only the newest version of a story (2 or higher), only while it is still waiting for a clip and no file was ever seen for it.
        scope=this or later, as for a new version; stories that no longer qualify are skipped and listed."""
        scope = (r.body or {}).get("scope") or "this"
        if scope not in ("this", "later"): raise HttpError(400, "scope must be this or later")
        with self.db.tx() as cur:
            c, mine, latest, rows = self.scope_of(cur, int(r.m[0]))
            if mine["version"] < 2: raise HttpError(409, "version 1 is the clip itself and cannot be deleted")
            if c["id"] != mine["id"]: raise HttpError(409, "only the newest version of a story can be deleted")
            gone, skipped = [], []
            for x in self.scope_targets(c, mine, latest, scope):
                if x["version"] < 2 or x["state"] != "WAITING_FOR_CLIP" or x["nfiles"]: skipped.append({"rundown": x["rundown"], "name_id": x["nm"], "why": "version 1" if x["version"] < 2 else "a file was already seen or it was already sent / attached"}); continue
                cur.x("DELETE FROM clip_ids WHERE id=?", (x["id"],)); gone.append(x)
            if not gone: raise HttpError(409, "nothing to delete: a version can only be deleted while it is still waiting for its clip (%s)" % (skipped[0]["why"] if skipped else "no version"))
            self.log(cur, r.user["username"], "version_deleted", {"name_id": mine["nm"], "display_ids": [x["display_id"] for x in gone], "scope": scope, "skipped": len(skipped)})
            return {"deleted": len(gone), "skipped": skipped, "name_id": mine["nm"]}
    def a_attached(self, r):
        """The desk looked at the story in Blaze and confirms the right clip is on the right story."""
        cid = int(r.m[0])
        with self.db.tx() as cur:
            row = cur.one("SELECT c.display_id, s.deleted AS story_removed FROM clip_ids c JOIN stories s ON s.id=c.story_id WHERE c.id=?", (cid,))
            if not row or not cur.x("UPDATE clip_ids SET state='ATTACHED', attached_at=?, attach_method='desk', attach_error=NULL WHERE id=? AND state IN ('ON_NITRO','NEEDS_DESK','ATTACH_SUBMITTED')", (now_iso(), cid)):
                raise HttpError(409, "clip must be ON_NITRO or NEEDS_DESK")
            self.log(cur, r.user["username"], "attached_by_desk", row); return row
    def a_preview(self, r):
        """v10.1.0: stream the clip's Nitro file as a small H.264 video (see preview.py). Needs login like every other /api call."""
        with self.db.tx() as cur: rows = cur.q("SELECT nitro_path FROM files WHERE clip_id=? AND nitro_path IS NOT NULL ORDER BY id DESC", (int(r.m[0]),))
        if not rows: raise HttpError(404, "This clip is not on Nitro yet")
        return preview.open_stream(rows[0]["nitro_path"])
    @staticmethod
    def story_clips(rows):
        """Story Media Gallery: every clip ID of ONE story (same bulletin) with what the gallery shows for it. role: original (plain clip), update (_Un), additional (_Vn) or version (old +Version number).
        The original comes first, then the others in the order they were created. on_nitro says whether the Play preview can work (the same test as the preview call: a Nitro file path is recorded)."""
        out = []
        for x in rows:
            v = int(x["version"] or 1); k = kind_of(v)
            role = "original" if v == 1 else "update" if k == "U" else "additional" if k == "V" else "version"
            out.append({"id": x["id"], "display_id": x["display_id"], "name_id": x["name_id"], "version": v, "role": role, "label": "BASE" if role == "original" else vlabel(v) if k else "V%d" % v,
                        "state": x["state"], "mos_object_id": x["mos_object_id"], "item_id": x["item_id"], "attach_dur": x["attach_dur"], "blaze_clip_id": x["blaze_clip_id"],
                        "replaced": bool(x.get("replaced_at")), "replaced_by": x.get("replaced_by"), "on_nitro": bool(x["_nit"]), "duration_s": x["duration_s"], "file": re.split(r"[\\/]", x["_nit"])[-1] if x["_nit"] else None})
        out.sort(key=lambda y: (y["role"] != "original", y["id"])); return out
    @staticmethod
    def script_items_of(raw):
        """v10.9.7: the stored JSON list of {n, online, anchor} (None for a story read before this version: the dashboard then shows the joined text in one box)."""
        try: v = json.loads(raw) if raw else None
        except ValueError: return None
        return v if isinstance(v, list) else None
    def a_history(self, r):
        """The story-to-media timeline of one clip ID for the detail panel: what happened, when, and what is still to come. Built only from what the registry recorded."""
        with self.db.tx() as cur:
            c = cur.q("""SELECT c.id, c.display_id, COALESCE(c.name_id, c.display_id) AS name_id, c.media_id AS mos_object_id, c.item_id, c.attach_dur, c.blaze_clip_id, c.version, c.state, c.created_at, c.verified_at, c.on_nitro_at, c.attached_at, c.attach_method, c.attach_error,
                         s.slug, s.story_title, s.online_script, s.anchor_script, s.script_items, s.script_at, s.blaze_story_id, s.position, s.deleted, s.created_by, s.assigned_to, s.editor, ru.name AS rundown, ru.start_at AS show_start, ru.blaze_rundown_id
                         FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id WHERE c.id=?""", (int(r.m[0]),))
            if not c: raise HttpError(404, "no such clip")
            files = cur.q("SELECT state, nas_path, nitro_path, size, duration_s, error, created_at FROM files WHERE clip_id=? ORDER BY id", (c[0]["id"],))
            sib = cur.q("""SELECT c.id, c.display_id, COALESCE(c.name_id, c.display_id) AS name_id, c.version, c.replaced_at, c.replaced_by, c.state, c.media_id AS mos_object_id, c.item_id, c.attach_dur, c.blaze_clip_id,
                         (SELECT nitro_path FROM files f WHERE f.clip_id=c.id AND f.nitro_path IS NOT NULL ORDER BY f.id DESC LIMIT 1) AS _nit,
                         (SELECT duration_s FROM files f WHERE f.clip_id=c.id AND f.duration_s IS NOT NULL ORDER BY f.id DESC LIMIT 1) AS duration_s
                         FROM clip_ids c WHERE c.story_id=(SELECT story_id FROM clip_ids WHERE id=?) ORDER BY c.id""", (c[0]["id"],))
            stored, _seen = self.stored_clips(cur, c[0]["blaze_story_id"])         # v10.17.0: what Blaze really holds in the story (clips added by hand included)
        c = c[0]; base = lambda p: re.split(r"[\\/]", p)[-1] if p else None
        seen = next((f for f in files if f["state"] in ("EXPORTING", "VERIFIED", "ON_NITRO", "QUARANTINED") and f["nas_path"]), None) or next((f for f in files if f["nas_path"]), None)
        nit = next((f for f in reversed(files) if f["nitro_path"]), None)
        step = lambda key, label, detail, time_, done, problem=False: {"key": key, "label": label, "detail": detail, "time": time_, "done": bool(done), "problem": problem}
        steps = [step("story", "Story received from Blaze", "Story %s in %s%s" % (c["blaze_story_id"], c["rundown"] or c["blaze_rundown_id"], (", row %s" % c["position"]) if c["position"] is not None else ""), c["created_at"], True),
                 step("id", "Auto-ID generated", c["name_id"] + ("" if c["name_id"] == c["display_id"] else "   (internal ID " + c["display_id"] + ")"), c["created_at"], True),
                 step("export", "Export detected", ("File seen in Playout: " + base(seen["nas_path"])) if seen else "Waiting for the export with exactly this name", seen["created_at"] if seen else None, seen),
                 step("nitro", "Nitro file detected", ("Converted file: " + base(nit["nitro_path"])) if nit else "Waiting for the converted file on Nitro", c["on_nitro_at"] or (nit["created_at"] if nit else None), c["on_nitro_at"] or nit),
                 step("attach", "Attachment verified" if c["attached_at"] else "Attachment in the story", ("Attached (%s)" % (c["attach_method"] or "seen in Blaze") + "".join(" · %s %s" % (k, v) for k, v in (("MOS object", c["mos_object_id"]), ("item", c["item_id"]), ("duration", None if c["attach_dur"] is None else "%d s" % c["attach_dur"])) if v not in (None, ""))) if c["attached_at"] else "Waiting for the desk (or the live attach) to put the clip in the story", c["attached_at"], c["attached_at"])]
        err = c["attach_error"] or next((f["error"] for f in reversed(files) if f["error"]), None)
        if err: steps.append(step("problem", "Needs the desk", err, None, False, True))
        if c["deleted"]: steps.append(step("removed", "Story removed from the rundown", "Check in Blaze where the clip belongs before marking it attached", None, False, True))
        first = next((f for f in files if f["nitro_path"] or f["nas_path"]), None); fl = nit or first
        return {"id": c["id"], "display_id": c["display_id"], "name_id": c["name_id"], "state": c["state"], "steps": steps, "story_clips": self.story_clips(sib) + self.hand_cards(stored, sib, c["blaze_story_id"]),
                "clip": {"slug": c["slug"], "story_title": c["story_title"], "online_script": c["online_script"], "anchor_script": c["anchor_script"], "script_items": self.script_items_of(c["script_items"]), "script_at": c["script_at"], "created_by": c["created_by"], "assigned_to": c["assigned_to"], "editor": c.get("editor"), "show_start": c["show_start"], "rundown": c["rundown"], "blaze_rundown_id": c["blaze_rundown_id"], "blaze_story_id": c["blaze_story_id"], "position": c["position"], "deleted": bool(c["deleted"]),
                         "mos_object_id": c["mos_object_id"], "item_id": c["item_id"], "attach_dur": c["attach_dur"], "blaze_clip_id": c["blaze_clip_id"]},
                "file": {"name": base((fl or {}).get("nitro_path") or (fl or {}).get("nas_path")), "where": "Nitro" if nit else ("Playout" if fl else None), "size": (fl or {}).get("size"), "duration_s": (fl or {}).get("duration_s")} if fl else None}
    def a_events(self, r):
        """The activity log, newest first. v10.9.5: hours=1|2|4 (any number up to 168) keeps only the last that many hours (the dashboard's Recent activity tab); without it: the newest `limit` rows as before."""
        try: n = max(1, min(int(r.q.get("limit", 100)), 500)); hrs = float(r.q["hours"]) if r.q.get("hours") else None
        except ValueError: raise HttpError(400, "limit must be a whole number and hours a number")
        if hrs is not None and not 0 < hrs <= 168: raise HttpError(400, "hours must be more than 0 and at most 168")
        with self.db.tx() as cur:
            if hrs is None: rows = cur.q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,))
            else: rows = cur.q("SELECT * FROM events WHERE time>=? ORDER BY time DESC, id DESC LIMIT ?", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hrs * 3600)), n))
        for x in rows: x["details"] = json.loads(x["details"] or "{}")
        return rows
    @staticmethod
    def feed_status(state, qa):
        """One word for where a clip with a file in Blaze's media list stands: READY (waiting to be attached), REQUESTED (a Quick test attach was confirmed), SUBMITTED (sent, being read back), ATTACHED, NOT_SENT (a Quick test was blocked or failed), NEEDS_DESK."""
        if state == "ATTACHED": return "ATTACHED"
        if state in ("NEEDS_DESK", "QUARANTINED"): return "NEEDS_DESK"
        if qa == "REQUESTED": return "REQUESTED"
        if state == "ATTACH_SUBMITTED": return "SUBMITTED"
        if qa in ("BLOCKED", "FAILED"): return "NOT_SENT"
        return "READY"
    FEED_TEXT = {"READY": "Ready to attach", "REQUESTED": "Attach requested", "SUBMITTED": "Attach sent", "ATTACHED": "Attached", "NOT_SENT": "Not sent", "NEEDS_DESK": "Needs desk"}
    FEED_GROUP = {"ready": ("READY", "REQUESTED", "SUBMITTED"), "attached": ("ATTACHED",), "problem": ("NOT_SENT", "NEEDS_DESK")}
    def a_feed(self, r):
        """v10.2.0 Ready feed: the clips of the day whose file is in Blaze's media list (the NITRO step is green), newest first, so nobody has to watch the chip. Each item: story name, clip ID, Blaze story ID, MOS object ID, media name, bulletin, when it became ready, and where it stands now. Parameters: day (YYYYMMDD, default today), q (every word must match the story, clip ID, Blaze story ID, MOS object ID, media name or bulletin), status (all, ready, attached, problem), limit (1 to 300, default 100). `counts` is for the whole day, whatever q and status say."""
        q = r.q; d = dt.datetime.strptime(q["day"], "%Y%m%d").date() if q.get("day") else self.today()
        try: limit = max(1, min(int(q.get("limit") or 100), 300))
        except ValueError: raise HttpError(400, "limit must be a number")
        st = (q.get("status") or "all").lower()
        if st != "all" and st not in self.FEED_GROUP: raise HttpError(400, "status must be all, ready, attached or problem")
        where, args = ["c.day=?", "c.media_found_at IS NOT NULL", "COALESCE(s.deleted,0)=0"], [d.isoformat()]
        bul = (q.get("bulletin") or "").strip()                                                            # v10.9.0: bulletin (Blaze show id) and username filters, like the dashboard's
        if bul: where.append("ru.blaze_rundown_id=?"); args.append(bul[:80])
        uc, ua = self.user_cond(q.get("user"))
        if uc: where.append(uc); args += ua
        ec, ea = self.editor_cond(q.get("editor"))
        if ec: where.append(ec); args += ea
        for w in (q.get("q") or "").lower().split()[:8]:
            like = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            cols = ("LOWER(s.slug)", "LOWER(COALESCE(s.story_title,''))", "LOWER(c.display_id)", "LOWER(COALESCE(c.name_id,''))", "LOWER(COALESCE(c.media_id,''))", "LOWER(COALESCE(c.media_name,''))", "s.blaze_story_id", "LOWER(ru.name)", "LOWER(COALESCE(s.created_by,''))", "LOWER(COALESCE(s.assigned_to,''))", "LOWER(COALESCE(s.editor,''))")
            where.append("(" + " OR ".join("%s LIKE ? ESCAPE '\\'" % c for c in cols) + ")"); args += [like] * len(cols)
        tbl = "FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id WHERE "
        with self.db.tx() as cur:
            rows = cur.q("SELECT c.id, c.display_id, COALESCE(c.name_id, c.display_id) AS name_id, c.version, c.state, c.qa_state, c.qa_msg, c.attach_error, c.media_id, c.media_name, c.media_found_at, c.attached_at, "
                         "s.blaze_story_id, s.slug, s.story_title, s.position, s.created_by, s.assigned_to, s.editor, ru.name AS bulletin, ru.start_at, ru.blaze_rundown_id " + tbl + " AND ".join(where) + " ORDER BY c.media_found_at DESC, c.id DESC", args)
            cnt = cur.q("SELECT c.state, c.qa_state, COUNT(*) AS n " + tbl + "c.day=? AND c.media_found_at IS NOT NULL AND COALESCE(s.deleted,0)=0 GROUP BY c.state, c.qa_state", [d.isoformat()])
            bl = cur.q("SELECT ru.blaze_rundown_id AS id, ru.name, ru.start_at AS start, COUNT(*) AS n " + tbl + "c.day=? AND c.media_found_at IS NOT NULL AND COALESCE(s.deleted,0)=0 GROUP BY ru.id ORDER BY ru.start_at IS NULL, datetime(ru.start_at), CAST(ru.blaze_rundown_id AS INTEGER), ru.id", [d.isoformat()])
            users = self.day_users(cur, d.isoformat(), "AND c.media_found_at IS NOT NULL AND COALESCE(s.deleted,0)=0"); editors = self.day_editors(cur, d.isoformat(), "AND c.media_found_at IS NOT NULL AND COALESCE(s.deleted,0)=0")
        counts = {"ready": 0, "attached": 0, "problem": 0, "all": 0}
        for x in cnt:
            k = self.feed_status(x["state"], x["qa_state"]); counts["all"] += x["n"]
            for g, members in self.FEED_GROUP.items():
                if k in members: counts[g] += x["n"]
        items = []
        for x in rows:
            k = self.feed_status(x["state"], x["qa_state"])
            if st != "all" and k not in self.FEED_GROUP[st]: continue
            items.append({"id": x["id"], "display_id": x["display_id"], "name_id": x["name_id"], "version": x["version"], "label": vlabel(x["version"]) if kind_of(x["version"]) else None, "kind": {"U": "update", "V": "added"}.get(kind_of(x["version"])), "blaze_story_id": x["blaze_story_id"], "story": x["story_title"] or x["slug"], "slug": x["slug"], "created_by": x["created_by"], "assigned_to": x["assigned_to"], "editor": x["editor"],
                          "bulletin": x["bulletin"], "start_at": x["start_at"], "blaze_rundown_id": x["blaze_rundown_id"], "position": x["position"], "state": x["state"], "qa_state": x["qa_state"],
                          "typed": x["blaze_rundown_id"].startswith("name:") or x["blaze_story_id"].startswith("manual-"), "mos_object_id": x["media_id"], "media_name": x["media_name"], "ready_at": x["media_found_at"], "attached_at": x["attached_at"],
                          "status": k, "status_text": self.FEED_TEXT[k], "reason": (x["qa_msg"] if k == "NOT_SENT" else x["attach_error"] if k == "NEEDS_DESK" else None)})
        return {"day": d.isoformat(), "items": items[:limit], "total": len(items), "counts": counts, "limit": limit, "bulletins": bl, "users": users, "editors": editors}
    def clips_csv(self, req):
        """The day's clip IDs as a CSV file (opens in Excel). It holds everything that matches the dashboard's current day, search, filter and show: all of it, not one page. Same login and permission as the dashboard; every export is written to the activity log."""
        req.user = self.authenticate(req, "view"); req.q = {k: v for k, v in req.q.items() if k not in ("per_page", "page")}
        d = self.a_clips(req); self.now()
        def hm(iso):
            try: return dt.datetime.fromisoformat(iso).astimezone(self._tz).strftime("%H:%M") if iso else ""
            except (ValueError, TypeError): return ""
        def cell(v):                                                       # a text that starts with = + - @ would run as a formula in Excel: it is written as plain text
            t = "" if v is None else str(v); return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t
        out = io.StringIO(); w = csv.writer(out, lineterminator="\r\n")
        w.writerow(["Clip ID", "State", "Version", "Slug", "Story name", "Bulletin", "Bulletin time", "Show ID", "Story ID", "Slug ID", "Row", "Created", "Removed from rundown", "Note", "MOS object ID", "Item ID", "Duration (s)", "Blaze clip ID", "Created by", "Assigned to", "Editor"])
        for c in d["clips"]:
            w.writerow([cell(x) for x in (c["display_id"], c["state"], c["version"], c["slug"], c["story_title"], c["rundown"], hm(c["show_start"]), c["blaze_rundown_id"], c["blaze_story_id"], c["slug_id"], c["position"], c["created_at"], "yes" if c["deleted"] else "", c["error"], c["mos_object_id"], c["item_id"], c["attach_dur"], c["blaze_clip_id"], c.get("created_by"), c.get("assigned_to"), c.get("editor"))])
        with self.db.tx() as cur: self.log(cur, req.user["username"], "clips_exported", {"day": d["day"], "rows": len(d["clips"]), "filter": req.q.get("filter") or "all", "show": req.q.get("show") or "", "user": req.q.get("user") or "", "q": req.q.get("q") or ""})
        req.filename = "autoid_clips_%s.csv" % d["day"].replace("-", "")
        return 200, ("\ufeff" + out.getvalue()).encode("utf-8"), "text/csv; charset=utf-8"

    def report_page(self, req):
        """The tool-vs-desk report the poller writes (data/reports/agreement_YYYYMMDD.html). /report is today's broadcast day, /report/20261107 a given day. Same login as the dashboard; only that file name pattern is ever read."""
        shell = lambda t, body: ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>%s</title><body style='font:16px system-ui;max-width:36rem;margin:2rem auto;padding:0 1rem'>%s" % (t, body)).encode()
        try: self.authenticate(req, "view")
        except HttpError: return 401, shell("Sign in", "<h2>Sign in first</h2><p>Open <a href='/'>the dashboard</a>, sign in, then open the report again.</p>"), "text/html; charset=utf-8"
        tail = req.path[len("/report"):].strip("/"); day = tail or self.today().strftime("%Y%m%d")
        if not re.fullmatch(r"\d{8}", day): raise HttpError(404, "not found")
        f = Path(self.cfg.get("reports_dir") or data_dir() / "reports") / ("agreement_%s.html" % day)
        if f.is_file(): return 200, f.read_bytes(), "text/html; charset=utf-8"
        return 404, shell("No report", "<h2>No report for %s yet</h2><p>The poller writes it about once a minute while it runs (BLAZE_POLL=1 and BLAZE_ATTACH=dry or live). <a href='/'>Back to the dashboard</a></p>" % day), "text/html; charset=utf-8"

    # ---------- routing ----------
