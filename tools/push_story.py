#!/usr/bin/env python3
"""Report one story to the running Auto-ID server, as a feed would (LINK_MODE=story_id): the ID is made from Blaze's own story ID.
  python3 tools/push_story.py --rundown-id RO123 --rundown-name "03_11 9 PM Bulletin" --story-id 2669125 --slug "EXP VNR AGRI"
Run it again for the same story: nothing changes (same story ID = same clip ID). Prints the clip ID."""
import argparse, json, os, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoid_lite import config
config.apply_env()
ap = argparse.ArgumentParser(); ap.add_argument("--rundown-id", required=True); ap.add_argument("--rundown-name"); ap.add_argument("--story-id", required=True); ap.add_argument("--slug", default="")
a = ap.parse_args()
req = urllib.request.Request("http://127.0.0.1:%s/svc/stories" % os.environ.get("WEB_PORT", "8080"), method="POST",
                             headers={"Content-Type": "application/json", "X-API-Key": os.environ["SERVICE_API_KEY"]},
                             data=json.dumps({"blaze_rundown_id": a.rundown_id, "rundown_name": a.rundown_name, "blaze_story_id": a.story_id, "slug": a.slug}).encode())
print(json.load(urllib.request.urlopen(req, timeout=10))["display_id"])
