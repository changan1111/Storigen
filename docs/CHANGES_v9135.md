# v9.13.5

* **New read-only command** `python3 tools/blaze_poll.py scripts <blaze story id>`: prints the keys of every item in versions[0] of `GET /stories/<id>/complete/`, the length of `text1` and `text2`, and what the poller would store (online / anchor). It finds out whether a card's "(empty in Blaze)" is real or the reader is missing the text.
* Nothing else changed.
