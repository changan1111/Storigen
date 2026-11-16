"""Tiny shared helpers."""
from __future__ import annotations
import time


def say(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
