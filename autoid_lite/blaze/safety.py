"""THE TECHNICAL WALL: the only writes this program can ever send to Blaze. Everything else raises ForbiddenCall before a request is built."""
from __future__ import annotations
import re


class ForbiddenCall(Exception): pass
# THE TECHNICAL BOUNDARY: reads are free; the only writes this program can ever send are the login (POST /sessions, v9.7.3), the session keep-alive, an attach, the undo of an attach, and the story's script-duration update that the Blaze page sends with every attach or delete.
# Anything else (editing a story, a rundown, a show, deleting anything but a clip) raises before a request is built, whatever the configuration says.
WRITE_ALLOWED = [("POST", r"/DataService/sessions"), ("PUT", r"/DataService/sessions/[^/]+"), ("POST", r"/DataService/stories/\d+/clips/"), ("DELETE", r"/DataService/stories/\d+/clips/\d+"), ("PUT", r"/DataService/stories/\d+/versions/\d+")]
def check_call(method, path):
    if method != "GET" and not any(method == m and re.fullmatch(p, path) for m, p in WRITE_ALLOWED): raise ForbiddenCall("%s %s is not an allowed call" % (method, path))
