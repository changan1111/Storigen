# v9.4 – complete-day polling engine, paged dashboard with search, show time and story name

A targeted upgrade of `tools/blaze_poll.py`. No new Blaze endpoint, no schema change, no change to the attachment write path or its safety rules.

## 1. What v9.3 did, and why that is not enough for 36 shows a day

| Limitation | Where | Effect at 36 shows / ~650 stories |
|---|---|---|
| Hot shows every pass, **cold shows every 120 s**, and a cold show is skipped while its slug *count* is unchanged | `Poller.due`, `Poller.sync` | an upcoming or finished show can change for two minutes unseen; a story replaced in a slug (count unchanged) is never noticed until the next cold read |
| Shows are read **one after another** | `Poller.sync` | the first pass and every cold pass is 36 sequential requests |
| **One failing show aborts the whole cycle** (any exception other than an expired session leaves `sync()`) | `Poller.sync`, `Poller.run` | the shows after it are not read, not synced, not planned |
| No snapshot, no change detection: the poller posts the list to the registry and forgets it | `Poller.sync` | nothing says *what* changed; nothing survives a restart |
| Attachments: a story is read only when its `clipCount` changed, or every `BLAZE_FULL_RECON_SECS` (600 s) | `Poller.reconcile` | a clip swapped for another while the count stays the same can stay unseen for 10 minutes |
| `reconcile` reads every story **sequentially**; first pass = every story | `Poller.reconcile` | ~650 requests in a row on start-up |
| Media-list search once per waiting clip, **sequentially**; the 30 s cache expires for all clips together | `Poller.plan` / `lookup` | ~650 requests in a row every other cycle once ~650 IDs exist |
| `time.sleep(poll)` after each cycle | `Poller.run` | the period is *cycle time + 15 s*; cycle time is never measured or reported |
| `Blaze.status` shared between calls; 15 s fixed timeout | `Blaze.call` | not safe to share between threads; one slow call can hold a cycle for 15 s |
| `/svc/clips` returns at most 500 rows | `server.s_clips` | with 648 stories, `plan`, `ready` and `reconcile` could not see the last ~150 |

## 2. What changed (exact functions)

**New module `tools/blaze_snapshot.py`** (stdlib, pure): `diff_show`, `diff_attachments`, `norm_rows`, `Fan` (bounded parallel reads with a deadline).

**`tools/blaze_poll.py`**
- `Cfg`: new settings (below). `BLAZE_MONITOR=hotcold` keeps the v9.3 rule.
- `Blaze`: `status` is per thread; timeout is `BLAZE_REQUEST_TIMEOUT`; `slugs()` also returns `slug_title` and `story_title`; `story_info()` rows also carry `item` (the clip's `itemId`).
- `Poller.sync` rewritten: all due shows are requested in parallel; each result is handled on its own; `apply` (new) diffs against the snapshot, stores it, and hands the list to the registry; `show_failed` (new) records a failure and schedules the retry.
- `Poller.due`: complete-day by default; failure back-off applies in both modes.
- `Poller.discover`: a failed list request keeps the known shows; a finished show Blaze stops listing is kept until the day closes.
- New tiers: `verify` (attachment identity), `observe` (every full story read compares clips), `read_stories`, `prefetch`; `reconcile` now reads its stories in parallel and skips a story whose read failed instead of aborting.
- `warm_media` (new): the media-list searches `plan` needs are made in parallel (same call, same cache).
- `cycle`: never overlaps (a lock), measures itself, reports overruns and stale shows; `run` keeps a fixed rhythm (`sleep(poll − cycle time)`).
- Reporting: `finish_stats`, `write_stats` (`reports/poll_stats.json`), `heartbeat_detail`, `stats_text`; CLI `stats`, `close-day`, `open-day`.
- `/svc/clips` is asked with `limit=5000`.

**`tools/blaze_ledger.py`**: `put_many`, `items`, `delete` (the existing key/value `meta` table; **no schema change**).

**`autoid_lite/server.py`**: `s_clips` accepts `limit` (default still 500, max 5000); `compute_health` adds the check `blaze_shows_fresh` when the poller's heartbeat carries `stale_shows`.

## 3. Request and concurrency strategy

```
every cycle (target 15 s, fixed rhythm, never overlapping)
  A  GET /shows/{id}/slugs            all due shows, parallel (BLAZE_CONCURRENCY, default 8)   -> diff vs snapshot
  B  GET /stories/{id}/complete/      stories whose clipCount moved (at once) + stories with clips
                                      that are older than BLAZE_ATTACH_VERIFY_SECS (≤ BLAZE_VERIFY_PER_CYCLE)
  C  GET /stories/{id}/complete/      reconcile: every story, every BLAZE_FULL_RECON_SECS (the v9.3 backstop), parallel
  once a minute: GET /shows?filter=… (the day's show list)
```

- **Thread safety.** Every request builds its own connection (`urllib`), so nothing is shared except the read-only session cookie; the one shared field (`status`) is now per thread. Worker threads do HTTP only. SQLite, the ledger, the registry calls and all state are touched by the cycle's own thread, with the results.
- **Deadline.** A cycle waits `BLAZE_CYCLE_DEADLINE_SECS` (default = poll). A request still running then keeps running, is **never started a second time**, and its answer is used by a later cycle. A request that had not started is cancelled and tried next cycle. Requests are bounded by `BLAZE_REQUEST_TIMEOUT`.
- **Failure isolation.** A failed show keeps its last snapshot, nothing is removed from the registry, and it is retried after 0, 1, 3, 3… cycles (≤ `BLAZE_RETRY_MAX_SECS`). A network or 5xx failure gets one quick retry while the cycle has time. A timeout is never an empty rundown; an *empty* answer for a show that had slugs is ignored too (`BLAZE_ALLOW_EMPTY=1` to accept). If Blaze answers none of the requested shows the cycle ends with `PollOutage` (shown as before), and the poller still reports its stale shows. An expired session is not retried: the cycle ends, snapshots are untouched, and the existing cookie recovery runs.
- **No overlap.** A lock makes a second `cycle()` call return at once (counted in `overlap_skipped`); per show and per story there is only ever one request in flight.
- **Registry.** A show's list goes to the Auto-ID registry when it changed, and at least every `BLAZE_SYNC_REFRESH_SECS` (60; 0 = every cycle as in v9.3). A registry failure keeps the snapshot and is retried.

## 4. Change detection

Per show, the latest slug list is compared with the snapshot (which is also stored in the ledger, `snap:<show>`):
`SLUG_ADDED`, `SLUG_REMOVED`, `SLUG_ID_CHANGED` (same story, new slug row), `STORY_REPLACED` (same slug row, other story: the count does not change), `SLUG_TITLE_CHANGED`, `STORY_TITLE_CHANGED`, `FORMAT_CHANGED`, `CLIP_COUNT_CHANGED`, `SLUG_MOVED`, `POSITION_CHANGED`.
An insert or delete shifts every later `finalPosition`; only rows outside the longest unchanged run are reported as moved.

Per story, the clips (`GET /stories/{id}/complete/`) are compared by **Blaze clip ID + media (MOS object) ID**, with title and duration as weaker evidence (`att:<story>` in the ledger):
`ATTACHMENT_ADDED`, `ATTACHMENT_REMOVED`, `ATTACHMENT_REPLACED` (a clip left and one arrived, or the same clip row points at another media object: **the count may stay the same**), `ATTACHMENT_CHANGED` (same clip and media object, other title or duration).

Everything is written to `attach_watch.log` (the desk's log) and, in full, to `reports/rundown_changes_YYYYMMDD.jsonl`. No change is reported for a first look (restart, new show) – only for differences from a stored snapshot.

### Attachment reconciliation trade-off

| Tier | Cost | Finds | Latency |
|---|---|---|---|
| A rundown (free: it is the slug list already read) | 0 extra | a clip *count* change, added/removed clip | one cycle (15 s) |
| B identity (`BLAZE_ATTACH_VERIFY_SECS`, default 120) | stories with clips ÷ interval reads/s | a clip replaced with the **same count** | ≤ interval + one cycle |
| C reconcile (`BLAZE_FULL_RECON_SECS`, default 600) | every story ÷ interval reads/s | everything, incl. stories with count 0 (guards against an unreliable `clipCount`) | ≤ 600 s |

Cost of tier B: *(stories with clips) ÷ interval*. 216 stories with clips at 120 s ≈ 1.8 requests/s; at 15 s (every cycle) ≈ 14/s. Set it to what the real Blaze tolerates; measure first.

## 5. Statistics (heartbeat, `poll_stats.json`, `blaze_poll.py stats`, the `POLL` line)

Shows discovered, slugs loaded, unique story IDs, show requests ok / failed / late / backing off, API time (avg, p95, max), cycle duration, overruns, last good read per show, changed stories, attachment changes, shows older than the freshness target. The status page shows `blaze_shows_fresh` red when shows have been stale for `STALE_SECS` (a short blip is not an alarm).

## 6. Blaze API limitations (what the captured traffic does and does not give)

- **No file hash, size or version in any endpoint used.** Replacement is detected by clip ID, media object ID, title and duration. A file overwritten in place behind the **same** media object with the **same** title and duration is **not detectable**.
- `clipCount` semantics are not documented (does it count every clip type?). It is only used as a *trigger*; tier B/C read the real clips. Verify against the real server.
- `GET /shows/{id}/slugs` has no "changed since" parameter; a full list per show per cycle is the cheapest verified call. The slug list's own `modifiedTime` was **not** used: it is not known whether Blaze updates it when a clip is replaced. If it does, it could trigger tier B at no cost – worth one experiment on the real server (`blaze_poll.py show <id>` before and after a replacement).
- The show list's `modifiedTime` does not move when stories are added (v9.3 finding), so it is not used.
- The unit of a show's `duration` is not verified; "finished" is judged from the start time (`BLAZE_HOT_BEFORE_MIN`).
- Real Blaze latency and its tolerance for ~2.4 requests/s (36 per 15 s) plus tier B/C reads are unknown. All numbers below are simulated.

## 7. Operating

- `BLAZE_MONITOR=hotcold` restores the v9.3 polling rule (back-off, snapshots and parallel reads still apply).
- `python3 tools/blaze_poll.py stats` – what the running poller measures. `close-day [YYYYMMDD]` / `open-day` – stop or resume following a broadcast day (the poller notices within one cycle; the day also closes by itself when it rolls over; snapshots stay as history; records older than `BLAZE_SNAPSHOT_KEEP_DAYS` are pruned when a day closes).
- One intentional test change: `test_hot_shows_are_read_every_pass_and_cold_ones_only_when_due_or_changed` now sets `BLAZE_MONITOR=hotcold`, because the behaviour it asserts is the one this upgrade replaces as the default. The fake Blaze became a threaded server with delay/failure hooks. Every other existing test is unchanged and passes.

## 8. Results (simulated: `python3 tests/bench_fullday.py --old <v9.3 blaze_poll.py> --latency <ms>`)

Same fake Blaze, 36 shows x 18 slugs = 648 stories (216 with a clip), fixed latency on every request, real HTTP, real Auto-ID server. Wall-clock seconds per cycle; target 15 s.

| 50 ms per request | v9.3 | v9.4 |
|---|---|---|
| first cycle | 61.5 s (1186 requests) | 9.1 s (1334) |
| steady cycle | 0.4 s (8 requests: hot shows only) | 0.3 s (36: every show) |
| media-search cache expires (every `BLAZE_MEDIA_RETRY_SECS`) | **26.2 s** (508) | 4.5 s (684) |
| full reconcile (every `BLAZE_FULL_RECON_SECS`) | **34.0 s** (657) | 4.5 s (684) |

| 150 ms per request | v9.4 |
|---|---|
| first cycle | 16.4 s (over the target once: what has not arrived by the deadline finishes in the background and is used next cycle) |
| steady cycle | 1.4 s |
| media-search burst / full reconcile | 13.1 s / 13.1 s |

v9.3 at 150 ms was not measured (it takes about 15 minutes). These are simulations: they show the shape (sequential vs parallel, bursts), not what the real Blaze will do. Measure on the real server before relying on 15 s.

Tests: 187 pass (152 v9.3 + 35 in `tests/test_poll_fullday.py`).

## 9. Dashboard (v9.4)
`autoid_lite/web/index.html`, plus two additive database columns.

- **Buttons:** All, **Ready on Nitro**, **Need attention**, **Waiting for clip**, **Exporting**, **Attached**, each with a count.
- **250 stories per page**, Previous/Next at top and bottom. Filter and search apply to the whole day, then it is paged; the page and the selected story survive the 5 s refresh.
- **Search box:** every word must match (so `flood 14:30` works). It looks in the clip ID, slug title, **story name**, **Blaze story ID**, **slug ID**, **show ID**, bulletin name and **bulletin time** (`14:30` or `1430`). Button counts follow the search.
- **Every story card shows:** slug title, story name, bulletin name + bulletin time + show ID, row, slug ID, story ID, clip ID.
- **Ready notice:** when a clip newly reaches Nitro: banner (click = show the Ready list), count in the tab title, optional beep (checkbox).
- **Data:** the poller now sends the show's start time (`rundown_start`, from the day's show list) and each story's own title (`story_title`) to the registry; new columns `rundowns.start_at` and `stories.story_title` are added automatically to an existing database (same additive pattern as `slug_id`). Rows show the time after the next poll cycle. In fixed-show mode (`BLAZE_SHOW_IDS`, no day list) there is no show time to send, so the card shows the bulletin name only; the search then still finds a time written in the name.
- **Bulletin time** is the show's start time shown in the browser's time zone, 24 h.
- Not browser-tested here: the JavaScript syntax, the search matching, the state-to-button mapping and the page maths were checked; the layout was not seen on a screen.
- **Two views** (buttons above the filters, remembered in the browser): **Plain list** (ready first, then by row, 250 per page) and **Group by bulletin time**, a split screen: on the left a column of bulletin times (time, name, show ID, story count, how many are ready / need attention / waiting), on the right the stories of the selected bulletin in row order. It opens on the first bulletin that has a ready clip, else the one on air now; the choice and the scroll position of the time list survive the 5 s refresh. Filters and search apply in both views: in the group view the left column lists only bulletins that still have matching stories. A bulletin is short, so the group view has no paging. On a phone or narrow window the two panes stack (times on top). Bulletins with no known time come last.
