# archiver - the shared bus client

The one Redis client every bus loop connects through, producers and consumers alike, and the
broker boundary it connects across. Split out of [BUS.md](BUS.md), the producing half; the
consuming half is [BUS_CONSUMERS.md](BUS_CONSUMERS.md).

## The shared client's connection policy (archiver#193)

All seven bus loops share one client from `src/core/changes/bus_client.py`, never a
bare `from_url` - safe only on loopback. That module holds the reasoning; three
facts that surprise:

- **`socket_timeout` has a floor.** redis-py does not extend it for a blocking
  command, so a value at or below a loop's `BLOCK` raises on every *idle* read.
  It derives from `read_windows.LONGEST_READ_BLOCK_MS` - a leaf module, so the
  client stays upstream of the loops - whose claim a test audits by discovery.
- **`socket_connect_timeout` bounds one attempt, not the call**:
  `(retries + 1) x socket_connect_timeout`. Both clients take **zero** retries -
  a redis-py retry re-sends the command, so one on `XADD` publishes a duplicate
  the outbox cannot see. The loops own retry; the client has no opinion.
- **`from_url` is lazy**, so an unreachable broker raises nothing at startup.
  `probe_bus_reachable` PINGs once and logs at ERROR, detached, password
  redacted - a down broker must not read as an idle one.

**Why any of this is needed:** the broker stopped being `localhost` at #193 and
is now a tailnet peer, so a partition is a thing that will actually happen
rather than a thing the code merely tolerates. It still degrades rather than
loses - the outbox is the durable buffer. The URL, the measured path, and the
`default:` username that is load-bearing for `redis-cli` (archiver#195):
[reference/tailscale.md](reference/tailscale.md).

Consumer loops need no transient/poison classification of their own; what they do
on a dropped connection is pinned by `tests/core/changes/test_bus_reconnect.py`.

## The broker boundary

**The broker is not operated from this repo (#193 D6).** Its tuning, health
probe, and stream inventory live in
[CannObserv/broker](https://github.com/CannObserv/broker); archiver is a client.
One seam survives that split with no test spanning it: the broker config's
`maxmemory` cap and `OutOfMemoryError` being transient in
`_TRANSIENT_PUBLISH_ERRORS` are **one decision**, and each repo names the other
in a comment (R5).

**Lockstep invariant (archiver#128) — now spans two REPOSITORIES (archiver#193 R5).** The broker config's `maxmemory` cap and `OutOfMemoryError` being listed in `_TRANSIENT_PUBLISH_ERRORS` (`src/core/changes/publisher.py`) are **one decision; never change either alone.** The cap now lives in `CannObserv/broker:deploy/redis.conf.broker`, so no test spans the pair — each side names the other in a comment and that is the whole mechanism. It rode a systemd drop-in overriding `ExecStart` while this repo tuned the broker; broker#1 Phase 5 appended it to `redis.conf` instead, because `requirepass` cannot ride an `ExecStart` argument without landing in `argv` and journald, and splitting the rest of the tuning across two mechanisms then buys nothing (archiver#196). `redis.conf.broker` is **not** a drop-in. `maxmemory-policy noeviction` with the default `maxmemory 0` is inert — nothing is ever refused, so an untrimmed stream is OOM-killed rather than erroring. The cap restores bounded, instance-wide `OOM command not allowed` errors; the transient classification is what stops those from dead-lettering valid `info.changes` events (`OutOfMemoryError` is a `ResponseError` subclass, so the default "possibly-permanent" branch would otherwise catch it). Removing the cap makes the classification pointless; removing the classification makes the cap lossy. The blast radius is instance-wide — **every** producer on the shared broker is refused, and every durable path retries through it: Archiver's outbox via this entry, Watcher's and Replicator's as verified in CannObserv/watcher#288 and CannObserv/replicator#79. At the cap the bus stalls rather than losing those writes. The periodic full-set publishes do not retry - `info.registry` snapshots, `content.fetch-policy` (Watcher's until F1, then Archiver's, archiver#366) and Watcher's `info.watch-status` - because the next period supersedes a lost one.

`ARCHIVER_REDIS_STREAM_MAXLEN` ([ENVIRONMENT.md](ENVIRONMENT.md)) moves a broker threshold:

**Setting this obliges a note to [CannObserv/broker](https://github.com/CannObserv/broker).** Their bus-health probe mirrors the *default* (`DEFAULT_STREAM_MAXLEN`, `src/core/changes/publisher.py`) as `CHANGES_PRODUCER_MAXLEN` (`FACT_PRODUCER_MAXLEN` until CannObserv/broker#60), which reaches `info.changes` only, and derives a stream-too-long warning threshold from it. Naming the source is not enough when an env var can move it underneath — an override here leaves their threshold stale with no commit in either repo (the CannObserv/broker#44 failure mode, agreed with broker-agent 2026-09-23). Unset in production as of 2026-10-22 (#326), so the mirror is correct today.

`ARCHIVER_REGISTRY_STREAM_MAXLEN` ([ENVIRONMENT.md](ENVIRONMENT.md)) moves two broker checks:

**Setting this obliges a note to [CannObserv/broker](https://github.com/CannObserv/broker)**, for the same reason as the fact-stream cap above: their `REGISTRY_PRODUCER_MAXLEN` mirrors this knob's *default* and feeds `REGISTRY_WARN_LENGTH`, the stream-too-long **ceiling**. It also bounds their shrink check (`entries-removed`, CannObserv/broker#42). That check has no threshold on what it counts, but it reports only **under** the mirrored cap (why: `DEFAULT_REGISTRY_STREAM_MAXLEN`'s docstring), so an override here moves **both** checks. **Lowered**, the shrink check fires at each trim at the real cap. **Raised past the 10% margin**, the ceiling fires early. **Within the margin**, neither fires. Unset in production as of 2026-10-22 (#326).

`ARCHIVER_DEV_REDIS_URL` ([ENVIRONMENT.md](ENVIRONMENT.md)) is dormant or a local throwaway broker, never an index on the shared one:

**Do not re-add a `.../1` recommendation: a logical DB index is not a boundary.** Redis ACLs cannot partition by index — any client that can reach db1 can `SELECT 0` — so isolation by index is isolation by good behaviour. The shared broker closes that axis with `databases 1` and no `+select` in archiver's ACL (after its 2026-09-10 incident, `docs/INCIDENT-2026-09-10.md` in [CannObserv/broker](https://github.com/CannObserv/broker)), so `.../1` there is `ERR DB index is out of range`. Nor is a scratch bus on the shared instance wanted: it shares `maxmemory` under `noeviction` instance-wide, so a dev run that fills it stalls every production publisher (the R5 lockstep, firing for a reason nobody would look for). A prefix-confined dev credential (`~archiver.dev.*`) is available from broker on request — not requested until a real need appears.
