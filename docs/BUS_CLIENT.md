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

**The broker is not operated from this repo (#193 D6).** Its tuning, health
probe, and stream inventory live in
[CannObserv/broker](https://github.com/CannObserv/broker); archiver is a client.
One seam survives that split with no test spanning it: the broker config's
`maxmemory` cap and `OutOfMemoryError` being transient in
`_TRANSIENT_PUBLISH_ERRORS` are **one decision**, and each repo names the other
in a comment (R5).
