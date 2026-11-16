"""Errors the Blaze client and the poller raise."""
from __future__ import annotations


class SessionExpired(Exception): pass
class LoginFailed(Exception): pass
class BlazeError(Exception):
    def __init__(self, code, body): super().__init__("Blaze answered %s: %s" % (code, (body or "").strip()[:300])); self.code, self.body = code, body
