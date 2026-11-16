# v9.4: complete-day polling engine, paged dashboard (changes on top of v9.3)

A targeted enhancement, not a rewrite. The watcher, the gateway, the Auto-ID database schema (`autoid_lite/db.py`), the existing ledger tables, the report, and every attach safety rule (dry by default, three locks for live, once per clip, read-back, kill switch, hourly limit, halt after 3 failures, the write allow-list) are unchanged. 177 tests pass (134 from v9.1 + 43 new or updated).

## 1. What was wrong in v9.3 (at 36 shows, 648 stories)
| Limitation | Effect |
|---|---|
| Shows were read one after another in one thread (about 310 ms each in the capture) | about 11 s of waiting for the slug lists alone; one slow request delayed every show behind it |
| One failing show raised an exception that ended the whole round | the other shows were not processed |
| Hot shows every round, cold shows every 120 s or when the story count changed | a story swapped for another (same count) in a cold show waited up to 2 minutes; finished shows were checked rarely |
| Change detection was only "slug count" and registry new/removed | swapped stories, retitled, moved, reformatted slugs and attachment changes were not reported |
| Reconcile skipped a story while its `clipCount` was unchanged (up to `BLAZE_FULL_RECON_SECS`) | a same-count attachment replacement stayed unseen |
| Reconcile read EVERY story in full, one by one, on its first pass and every 600 s | 648 x 167 ms = 108 s stall |
| The plan step searched Blaze's media list once per clip and read each found story in full, one by one | 600 single requests per round |
| `/svc/clips` returned at most 500 rows | **a day of 540 to 720 stories was cut off: clips beyond the 500th were never planned, reconciled or reported** (found by the 648-story test) |
| Nothing was stored between runs | a restart lost every baseline |
| No timings, no per-show state | no way to see a slow or stale show |
| An expired session is a **404** `{"errors":["authenticationFailed"]}` in the capture, not 401/403 | it would have been treated as an ordinary error |

## 2. The engine now
**Rounds.** One round every `BLAZE_POLL_SECS` (15), started on a fixed rhythm: the sleep is the interval minus the time the round took. Two rounds never run at once (a second call is skipped and counted). The round duration is measured, and a round over the target is logged (`POLL SLOW`) and counted.

**Layer A, every round, every show.** `GET /shows/<id>/slugs` for ALL of the day's shows (finished, running, upcoming), at most `BLAZE_CONCURRENCY` (6) at a time. Workers only talk to Blaze; every database and registry write happens in the main thread. Each result is compared with the stored snapshot and these changes are detected: new slug, removed slug, story replaced in a slug (even when the count is unchanged), story moved to another slug, slug title, position/order, story format, clip count, clip total duration, clip status. The slug list carries `clipCount`, `clipDur`, `clipStatus` and `cgCount` for every story at no extra cost; all 40 attaches and 4 deletes in the capture moved `clipCount` and `clipDur`.

**Layer B, attachment identity.** `GET /stories/<id>/clips?clipType=media` (about 16 ms; `/complete/` was about 167 ms) gives Blaze clip ID, media object ID, `objId`, title, duration, position, status. It is read when layer A's signals change, when a story is first seen, and every `BLAZE_IDENT_SECS` (120) as a sweep (at most `BLAZE_IDENT_BATCH` per round). Reported: `ATTACHMENT ADDED`, `REMOVED`, `REPLACED` (a clip left and another arrived, count unchanged; or the media behind a clip ID changed), `CHANGED` (same media, other name or length).

**Layer C, full reconciliation.** The existing `/complete/` read (story title, items), now in bounded batches (`BLAZE_RECON_BATCH` 60 per pass, oldest first) and in parallel, at `BLAZE_FULL_RECON_SECS` per story. It also records the STORY title (which differs from the slug title in 35 of 328 captured stories) and reports `STORY TITLE CHANGED`. Layers A and B hand a story to the reconcile at once when they see its attachments change.

**Failures.** A show that fails (timeout, 5xx) keeps its last good snapshot and is retried: next round, then after the poll interval x1, x2, x4 ... up to `BLAZE_RETRY_MAX_SECS`. A timeout is never an empty rundown, and an empty answer for a show is not applied. Nothing is deleted because a request failed. If Blaze answers for none of the shows, the round fails as before (silence turns the status pill red). A session expiry is recognised (404 `authenticationFailed`, 401, 403) and recovers when the cookie is renewed.

**Memory.** Slugs, clips, story titles, per-show poll state and a change log are stored in the poller's own ledger database (new tables only, `CREATE TABLE IF NOT EXISTS`; 14 days kept). A restart compares against what was seen before it, so changes made while the poller was off are found and nothing is reported twice. Slugs that left a rundown stay in the history, marked gone.

**Monitoring.** Per round: shows, slugs, unique stories, successful and failed show requests, API response time (median, p95, max), round duration and the time of each phase, last successful read per show, changed stories, attachment changes, shows over the freshness target. They go to the log (`POLL ...`, once a minute and whenever something changed or failed), to `data/reports/poll_stats.json`, to the Auto-ID heartbeat, and `python3 tools/blaze_poll.py stats` prints them. Shows not read for more than `BLAZE_STALE_SECS` (90) and repeated slow rounds appear as a problem on the dashboard status pill and raise the existing alert.

**Other fixes made on the way.** The plan step now searches Blaze's media list and reads story details in bounded parallel batches (`BLAZE_MEDIA_BATCH` 40, `BLAZE_INFO_SECS` 60) instead of one request per clip per round, and no longer prints a line for each of 600 clips still waiting for an export. `/svc/clips` no longer stops at 500 rows (5000 default). Keep-alive follows the page's rhythm (`BLAZE_HEARTBEAT=page`: GET every minute, PUT every 8 minutes; both seen over 2.2 hours).

## 3. Before and after (simulation, not a real Blaze)
`tools/bench_polling.py` replays response times taken from the capture (deciles: slug list median 310 ms and up to 1.06 s, `/complete/` 167 ms, clip list 16 ms, show list 28 ms, media search 66 ms with a long tail) for 36 shows x 18 slugs (648 stories, about 40 % with one clip). Same fake Blaze and the same Auto-ID server for both runs.

| | v9.3 | v9.4 |
|---|---|---|
| First round (initial synchronization) | 240.8 s, 1185 requests | **6.5 s**, 397 requests |
| Steady round, nothing changed | 98.8 / 108.2 / 110.0 s, 509 to 537 requests | **4.2 / 4.4 / 4.9 s**, 76 requests |
| Round with 6 changes | not measured (the run ended before it) | 6.2 s, 138 requests; 8 change events recorded |
| Clips looked at | 500 of 648 (the 500-row cap) | 648 |
| Against the 15 s target | 6.6 to 16 times over | met, with about 3x headroom, in this simulation |

The target is a scheduling objective: a round only meets it when Blaze answers at about the captured speed. Against a slower Blaze, or with fewer than 6 requests allowed in parallel, the engine reports `POLL SLOW` and the counters show it. 15-second monitoring has been measured only in this simulation.

## 4. Trade-offs you can tune
- **Same-count replacement.** A clip swapped for another of the SAME length changes nothing in the slug list. It is found by the identity sweep, so the worst-case delay is `BLAZE_IDENT_SECS` (120) plus one round. Lowering it costs requests: about 300 stories with clips means 2.5 requests/s at 120 s, 20 requests/s at 15 s. A swap of a different length is seen in the next round. (In the benchmark's busy round, one of three attachment changes was such a same-length swap: it was reported by the next sweep, as designed.)
- **Story title** changes (not the slug title) are found at the full reconciliation, or when the slug title changes.
- **Concurrency.** 6 matches the page's own bursts (8 within 2 s). Blaze's limits are not known; raise it only if Blaze copes.

## 5. Blaze limitations found (from the captures)
- The slug list has no story-level modified time, and the show's `modifiedTime` does not change when stories are added (all 05:40 in the capture). Only counts, durations and ids can be compared.
- The story title exists only in `/complete/` (and differs from the slug title in 35 of 328 cases).
- Media identity is `clip id`, `mosObjectId`, `objId`, title, duration, position, status, createdTime. There is no file hash or version number, so a new file saved under the same media object, name and length cannot be told apart. This is NOT claimed to be detected.
- It is not known whether `objId` changes when a file is re-exported.
- `clipCount` counts media clips; CG clips are counted separately (`cgCount`, `?clipType=cg`).
- An expired session is `404 {"errors":[" authenticationFailed"]}`. Session lifetime without keep-alive, rate limits and the maximum parallelism are not known.

## 6. Dashboard: paging
A day has 540 to 720 stories, so the list is now paged on the server: `GET /api/clips?page=&per_page=&filter=&show=&q=` (25, 50, 100 or 200 per page; filter all/action/waiting/done; one show; search in story name, clip ID, Blaze story ID with `%` and `_` taken literally). The counts on the cards cover the whole day. Page controls sit above and below the list; the story detail stays open when you change page. Calling `/api/clips` without parameters still returns everything.

## 7. Tests
| # | Scenario | Test |
|---|---|---|
| 1 | discovery of all 36 shows | `test_01` |
| 2 | initial load of 648 slugs, in parallel | `test_02` |
| 3 | all 36 shows refreshed each round | `test_03` |
| 4 | new slug in an upcoming show | `test_04` |
| 5 | story replaced, slug count unchanged | `test_05` |
| 6 | slug deleted, history kept | `test_06` |
| 7 | slug reordered | `test_07` |
| 8 | slug title and story title changed | `test_08` |
| 9, 10 | attachment added, removed | `test_09`, `test_10` |
| 11 | replaced with the count unchanged (signals, identity sweep, same clip ID) | `test_11` |
| 12 | one show times out | `test_12` |
| 13 | several shows fail, backoff, total outage | `test_13` |
| 14 | session expires and recovers (404 authenticationFailed) | `test_14` |
| 15 | a round longer than the target; no overlapping rounds | `test_15` |
| 16 | restart keeps snapshots and finds changes made meanwhile | `test_16` |
| 17 | completed shows stay in the snapshot and are still checked | `test_17` |
| 18 | one story ID in two shows | `test_18` |
| | every kind of change in `diff_show`; keep-alive rhythm; stale shows reach the status pill; paging, filters, search | `test_polling_engine.py`, `test_dashboard.py` |

Not tried on a real Blaze, Nitro or Windows PC.
