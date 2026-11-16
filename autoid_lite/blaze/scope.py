"""Plain-words description of what live attach is currently allowed to do (shown at start-up, in quicktest and in live)."""
from __future__ import annotations


def live_scope_text(c):
    """One line: where real attaching is allowed right now."""
    part = []
    if c.qt_stories: part.append("QUICKTEST: only Blaze story " + ",".join(sorted(c.qt_stories)))
    if c.qt_shows or c.qt_masters: part.append("QUICKTEST: only show " + ",".join(sorted(c.qt_shows) + ["slot " + x for x in sorted(c.qt_masters)]))
    if c.live_shows or c.live_masters: part.append("only shows " + ",".join(sorted(c.live_shows) + ["slot " + x for x in sorted(c.live_masters)]))
    return " and ".join(part) if part else "for ALL followed shows"
