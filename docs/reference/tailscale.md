# Tailscale - the archiver host's network

How this service reaches the change-bus broker now that neither shares a host
with the other (#193). Companion to [DEPLOYMENT.md](../DEPLOYMENT.md).

exe.dev VMs are **isolated from each other** - "there is not a private network
which connects them." Until #193 archiver reached the broker over `localhost`
because it *operated* the broker on its own VM. It no longer does either. A
tailnet replaces that hop.

The cluster-wide primer lives in `CannObserv/observo`
`docs/reference/tailscale.md` (what a tailnet is, WireGuard, MagicDNS, the
coordination server not being in the data path). This file covers only what is
specific to archiver.

## This deployment

- **Tailnet:** `cannobserv.org.github`, tied to the CannObserv GitHub org - so
  nodes are org-owned rather than owned by one person's login.
- **This node:** MagicDNS name `archiver`, tag `tag:archiver`, address
  `100.109.138.101`. **Non-ephemeral and tagged**, so it never expires.
- **The one peer that matters:** `broker`, `tag:broker`, `100.97.91.19` - the
  Redis change bus (CannObserv/broker#1). This is archiver's only tailnet
  destination.
- **Also on the tailnet, and irrelevant to archiver:** `watcher`
  (`100.120.218.69`), `notifier` (`100.98.9.17`), and the *user-owned*
  `observo-primary` (`100.105.63.31`, not tagged - reached by a `hosts` entry
  in the ACL rather than by tag).

### The node is named `archiver`; the machine is named `co-registrar`

Two names, two resolvers, one host:

```
$ getent hosts archiver
100.109.138.101 archiver.taild0fb76.ts.net      # MagicDNS -> the tailnet
$ getent hosts co-registrar
10.42.0.42      co-registrar.exe.xyz            # exe.dev's DNS -> the VM's eth0
```

Both answer, and **so does everything else**: `http://archiver:8000/health`,
`http://co-registrar:8000/health`, `http://127.0.0.1:8000/health` and
`http://$(tailscale ip -4):8000/health` all return 200 from this VM.

That is D3 working as designed - the bind is `0.0.0.0`, so every interface
answers - and it is also the trap. **A URL that works here tells you nothing
about which path it took.** notifier#43 lost an afternoon to the sharper form
of this (Ubuntu maps the short hostname to `127.0.1.1`, so the name resolves
locally instead of through MagicDNS, and nothing is listening). This host has
no such `/etc/hosts` line, and the `0.0.0.0` bind would mask it anyway - which
makes the quiet version worse, not better: a broken tailnet is invisible from
this VM's own `curl`.

**Verify the tailnet from the peer, or by address.** `tailscale ping broker`
and `tailscale status` are the honest checks; an HTTP 200 on a short name is
not one.

### ACL

```jsonc
{
  "tagOwners": {
    "tag:archiver": ["autogroup:admin"]
  },
  "acls": [
    // Archiver is a broker client and nothing else. No rule lists tag:archiver
    // as a dst: its HTTP surface is proxy-gated (D3) and has no machine caller
    // (D4). Its GCS egress goes to the internet, not across the mesh.
    { "action": "accept", "src": ["tag:archiver"], "dst": ["tag:broker:6379"] }
  ]
}
```

> **Peer visibility follows `acls`, not `ssh`.** An `ssh` block alone does not
> make a node reachable - it governs Tailscale SSH once the peer is already
> visible. Both blocks are needed for an administered node, and assuming
> otherwise costs a second policy edit before anything works.

**ACL granularity is per-VM, not per-service** - but that no longer costs
archiver anything, because #193 gave it a VM of its own. On the shared host
`tag:watcher` had granted tailnet access to watcher *and* archiver *and*
replicator.

The ACL does **not** open port 22. Administering this host goes over
`ssh archiver` (Tailscale SSH) or the public `co-registrar.exe.xyz`.

## The bind, and the boot race archiver does not have

This host binds **`0.0.0.0:8000`**, behind the exe.dev HTTPS proxy's login
gate. Not a tailnet-only bind, and that is a decision (D3), not an oversight:
the dashboard's entire identity model is proxy-injected `X-ExeDev-UserID` /
`X-ExeDev-Email` headers, so a tailnet-only bind has no proxy in front of it
and **no operator could log in**.

The consequence worth stating plainly: **notifier#43's R1 does not apply
here.** There is no `tailnet_bind.sh`, no `serve.sh`, no wait-for-address
`ExecStartPre`, and no startup race - because nothing on this host binds an
address tailscaled has to assign first. Loopback `curl` keeps working from the
first second of boot.

The broker node *does* carry that race, and solves it there. See
`CannObserv/broker:deploy/redis-server.dropin.conf`.

## Reaching the broker

`ARCHIVER_REDIS_URL` is `redis://default:<password>@broker:6379/0` - a MagicDNS
short name, resolved by tailscaled.

Two things about that URL that are not cosmetic:

- **`default:` is load-bearing.** The empty-username form
  `redis://:<password>@...` authenticates for redis-py and **fails** for
  `redis-cli`, which sends a two-argument `AUTH "" <password>` and gets
  `WRONGPASS`. The service comes up green while every shell tool degrades
  silently - which is exactly how `scripts/check_redis_floor.sh` went blind on
  two services during the cutover (archiver#195).
- **The hostname, not the address.** A tailnet IP is stable for the life of the
  node registration, but the name survives a re-registration and the address
  does not.

Path quality, measured: **1 ms, direct** (not DERP-relayed) from this node to
`broker`, both being in the same region. Cross-region and relayed the same hop
measured 36-40 ms during the migration. `tailscale status` names the path:

```
100.97.91.19  broker  tagged-devices  linux  active; direct 16.145.19.221:13218
```

`direct` is the word to look for. `relay "xxx"` there means DERP, and a
consumer loop waking from idle pays that on its cold path.

## Joining or re-joining this host

```bash
# Key staged in a 0600 file, never in argv - PAM audits argv into journald
# (observo#264). Generate it Pre-approved + Tagged + NOT Ephemeral.
sudo install -m 600 /dev/null /run/ts.key
sudo tee /run/ts.key >/dev/null <<< 'tskey-auth-...'
sudo systemctl enable --now tailscaled
sudo tailscale up --auth-key=file:/run/ts.key --hostname=archiver
sudo shred -u /run/ts.key
```

**Shred outside `set -euo pipefail`, or shred before you can fail.** During
#193's provisioning `tailscale up` exited non-zero on an SSH-ACL *warning*, the
script aborted under `-e`, and the shred never ran - leaving the auth key in
`/exe.dev/setup` and in journald. `--setup-script` runs once at first boot and
cannot be re-run, so the cleanup has to be unconditional.

**Tags bind at device registration.** Re-authenticating an existing node with a
differently-tagged key does *not* retag it - `tailscale up --reset` leaves the
old tags in place. Changing them takes `tailscale logout` followed by a fresh
`tailscale up`, which re-registers. Cheap on a new host; disruptive on one
peers already depend on, so **get the tag right before the first join.**

A key scoped to more than one tag applies *all* of them and cannot be narrowed
with `--advertise-tags`. Generate one single-tag key per node.

## DNS

`tailscale up` takes over `/etc/resolv.conf`, pointing it at MagicDNS
(`100.100.100.100`). Short names then resolve with nothing to maintain, which
is what makes `redis://...@broker:6379/0` legible.

**Check `CorpDNS` when a service cannot resolve a peer.** MagicDNS is a
per-node preference and it can be off while `tailscale status` looks perfectly
healthy - the node is up, the peers are listed, and every name lookup still
fails:

```bash
tailscale debug prefs | grep CorpDNS     # must be true
sudo tailscale set --accept-dns=true     # if it is not
```

During #193's cutover this was false on the watcher VM and took down watcher,
replicator and archiver simultaneously with `Error -5` (name resolution). It
stayed hidden because the checks that had been run were an IP-based probe from
that host and a name-based probe from *this* one - neither of which exercises
the broken thing.

## Token vocabulary

| Token | Direction | Where |
|---|---|---|
| Tailscale **auth key** (`tskey-auth-...`, pre-approved + tagged + non-ephemeral) | this VM -> joins the tailnet | admin console -> staged 0600, shredded after join |
| exe.dev **API token** (`exe1....`) | agent -> `POST https://exe.dev/exec` | operator's `.env` as `EXE_API_TOKEN`; the `cmds` scope has to name `ssh` and `set-region` explicitly if they are needed |
| Redis `requirepass` (inside `ARCHIVER_REDIS_URL`) | archiver -> broker | `/etc/archiver/.env`, unit-scoped |
| `X-API-Key` | caller -> archiver | `information.api_keys`; **zero rows** - there is no machine caller (D4) |

Independent secrets for independent hops. A tailnet key never authenticates a
Redis connection, and the Redis password is not what gets a host onto the
tailnet.
