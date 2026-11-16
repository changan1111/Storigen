"""Poller: the tool-vs-desk agreement report and its pages."""
from __future__ import annotations
from pathlib import Path
import datetime as dt
import os
import time
from . import ledger as bl
from .util import say


class ReportMixin:
    def five_days(self, n=5, end=None):
        """One dict per broadcast day, oldest first: {day, clips, rate, decided, counts}. Reads the registry only."""
        end = end or self.server_day(); out = []
        for k in range(n - 1, -1, -1):
            d = end - dt.timedelta(days=k); rows = self.a.call("/svc/clips?day=%s" % d.strftime("%Y%m%d")); res, sm = bl.build(self.led, rows, overdue_s=self.c.overdue)
            out.append({"day": d.isoformat(), "clips": len(res), "rate": sm["rate"], "decided": sm["decided"], "counts": sm["counts"]})
        return out
    def report(self, day=None, write=True, csv=True, five=None):
        """Text for the console, plus (write=True) the day's CSV and the styled HTML page the web app serves at /report. csv=False rewrites only the HTML (used every minute, so an open Excel file is never touched)."""
        d = day or self.server_day(); rows = self.a.call("/svc/clips?day=%s" % d.strftime("%Y%m%d"))
        res, summ = bl.build(self.led, rows, overdue_s=self.c.overdue); txt = bl.text(d.isoformat(), res, summ)
        if write:
            rp = Path(self.c.reports)
            if csv: bl.write_csv(rp / ("agreement_%s.csv" % d.strftime("%Y%m%d")), res)
            five = five if five is not None else self.five_days(5, d)
            have = {x.name[10:18] for x in rp.glob("agreement_????????.html")} if rp.exists() else set(); ds = d.strftime("%Y%m%d")
            nav = {"prev": max((x for x in have if x < ds), default=None), "next": min((x for x in have if x > ds), default=None)}
            page = bl.render_html(d.isoformat(), res, summ, {sh: nm for sh, (nm, _) in self.names.items()}, five, self.c.attach, time.strftime("%Y-%m-%d %H:%M:%S"), nav)
            rp.mkdir(parents=True, exist_ok=True); tmp = rp / ("agreement_%s.html.tmp" % ds); tmp.write_text(page, encoding="utf-8"); os.replace(tmp, rp / ("agreement_%s.html" % ds))     # the page is never half-written
        return txt
    def write_page(self):
        """Refresh today's HTML report (about once a minute). Never lets a report problem stop polling."""
        try:
            if time.time() - self.five_at > 300 or self.five is None: self.five = self.five_days(5); self.five_at = time.time()
            self.report(write=True, csv=False, five=self.five)
        except Exception as e:
            if str(e) != self.page_err: say("could not write the HTML report: %s: %s" % (type(e).__name__, e)); self.page_err = str(e)
    def summary(self, n=5):
        """Tool-vs-desk agreement for the last n broadcast days, one line per day, and the total: the table to read before deciding about live attach."""
        lines = ["Tool vs desk, last %d days (agreement = AGREE / decided clips)" % n]; agree = decided = days = 0
        for f in self.five_days(n):
            c = f["counts"]; agree += c["AGREE"]; decided += f["decided"]; days += 1 if f["decided"] else 0
            lines.append("  %s  clips %-3d  " % (f["day"], f["clips"]) + ("agreement %3.0f%% of %-3d" % (100 * f["rate"], f["decided"]) if f["rate"] is not None else "nothing to compare yet   ") + "  " + ", ".join("%s %d" % (x, c[x]) for x in bl.ORDER if c[x] and x != "AGREE"))
        lines.append("  total: " + ("%.0f%% of %d attached clips on %d day(s) with data" % (100 * agree / decided, decided, days) if decided else "nothing to compare yet"))
        return "\n".join(lines)
    def daily(self):
        today = self.server_day(); last = self.led.get("last_report_day")
        if last is None: self.led.put("last_report_day", today.isoformat())
        elif last < today.isoformat():
            say("\n" + self.report(today - dt.timedelta(days=1))); self.led.put("last_report_day", today.isoformat())
