"""Clip states: ONE place for the server and the Blaze poller.

A clip normally moves  WAITING_FOR_CLIP -> EXPORTING -> VERIFIED -> ON_NITRO -> ATTACH_SUBMITTED -> ATTACHED.
NEEDS_DESK and QUARANTINED are the side exits (the desk takes over / the file is set aside).
"""
STATES = {"WAITING_FOR_CLIP", "EXPORTING", "VERIFIED", "ON_NITRO", "ATTACH_SUBMITTED", "ATTACHED", "NEEDS_DESK", "QUARANTINED"}
LIVE_STATES = ("WAITING_FOR_CLIP", "EXPORTING", "VERIFIED", "ON_NITRO")      # clips that may still need attaching
