"""Blaze poller engine (stdlib only).

errors / safety / states / keys / scope / settings / client : small, pure or I/O-light building blocks
ledger / snapshot                                          : the poller's own SQLite ledger and the per-round snapshot store
poller (+ media, attach, reports, loop mixins)             : the Poller itself, split by what each group of methods does
Command line: tools/blaze_poll.py (unchanged commands).
"""
