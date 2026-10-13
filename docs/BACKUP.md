# archiver — the nightly backup (archiver#233)

`archiver-backup.timer` runs `python -m src.core.backup` at 03:17 UTC (10 min jitter,
`Persistent=true`). It dumps `archiver` with `pg_dump --format=custom`, verifies the archive
twice (`pg_restore --list` must show data for `information.alembic_version` and
`information.info_items`; `pg_restore --file=/dev/null` must read every block), and creates
`gs://co-gcs-archiver-backup/<hostname>/<UTC basic ISO>.dump`, e.g.
`co-registrar/20261014T031702Z.dump`. Then one check-in to Status's `co-archiver-backup`.
Ported from CannObserv/watcher's `watcher-backup` (watcher#296, #297); the rules are in
`src/core/backup.py`, the restore in `src/core/restore.py`.

| Property | How it holds |
|---|---|
| No database credential | the unit runs as system user `archiver_backup`; peer auth maps it to the role of the same name, which has `pg_read_all_data` + `CONNECT` on `archiver` and nothing else (`scripts/setup-backup-role.sql`). Not `exedev`: its #348 allowlist would make the dump silently incomplete. Not `archiver`: the owner can write |
| No privilege | `CapabilityBoundingSet=` empty, `ProtectSystem=strict`, `ProtectHome=yes`, a private `/tmp` for the dump; no env file, no `ARCHIVER_ALLOW_PRODUCTION_DB` (`pg_dump` by name never meets `db_safety`) |
| Keys never in an environment | `LoadCredential=gcs:/etc/archiver/co-archiver-backup.json` (no fallback: no key, no start, `243/CREDENTIALS`) and the tenant's `status-checkin-key`, drift's, with an empty fallback. `GOOGLE_APPLICATION_CREDENTIALS=%d/gcs`; a value from anywhere else is refused, exit 2 |
| Create-only | `if_generation_match=0`; a 412 is `unchanged` only when the stored sha256 matches, else a failure. The writer SA holds `objectCreator` + `objectViewer`, no delete. Retention is the bucket's lifecycle rule (`Delete age:30`), so a compromised host cannot erase its history |
| Never blocks a migration | `pg_dump --lock-wait-timeout=30s` gives up rather than queue. A migration that meets the dump's ACCESS SHARE fails on its own 5 s `lock_timeout` ([DEPLOYMENT.md § `scripts/deploy.sh`](DEPLOYMENT.md#scriptsdeploysh)), switches nothing, and a rerun works. The dump takes about a second |
| Loud failure, loud silence | exit 0 shipped, 1 failed, 2 misconfigured; `ok`/`alert` to co-status; the monitor goes `missing` when neither arrives. A failed check-in never changes the exit code |

**Personal data.** The dump holds `app_users.email`/`external_id` and `api_keys.key_hash`.
The bucket is private: uniform access, public-access prevention, Google-managed encryption
at rest; no public access, and objects readable only by the writer SA and principals
with project-level storage roles. A restore writes `0600` files
in a `0700` directory it owns, and refuses any other. CMEK or client-side encryption would
be a follow-up, not part of #233.

**What a check-in carries**, for the monitor's templates: an `alert` sends `source_host`,
`outcome` (`failed`) and `error`, with `metadata.fault` `failed` or `misconfigured`; an `ok`
sends `outcome` (`uploaded` or `unchanged`), `object`, `dumped_at`, `size_bytes`, `sha256`,
`alembic_head`, `source_host`. **No monitor id**, as until co-status creates it: the run
warns that a stop will not be noticed and exits on the backup's own result. **Never run it
with the real monitor id outside the unit**: a stray `ok` resets the dead-man clock.
`tests/conftest.py` scrubs `CO_ARCHIVER_BACKUP_MONITOR_ID`, `ARCHIVER_BACKUP_BUCKET` and
`GOOGLE_APPLICATION_CREDENTIALS`.

## Provisioning (once; operator)

**1. GCP**, by the owner of project `co-gcs`: watcher's commands with `watcher` →
`archiver`. The host has no `gcloud` and no credential that can do this.

```bash
PROJECT=co-gcs BUCKET=co-gcs-archiver-backup SA=co-archiver-backup
gcloud storage buckets create "gs://$BUCKET" --project="$PROJECT" --location=<same as co-gcs-blobs> \
    --uniform-bucket-level-access --public-access-prevention
printf '{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}\n' > /tmp/lifecycle.json
gcloud storage buckets update "gs://$BUCKET" --lifecycle-file=/tmp/lifecycle.json
gcloud iam service-accounts create "$SA" --project="$PROJECT" --display-name="co-archiver DB backup writer"
for role in roles/storage.objectCreator roles/storage.objectViewer; do
    gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
        --member="serviceAccount:$SA@$PROJECT.iam.gserviceaccount.com" --role="$role"
done
gcloud iam service-accounts keys create co-archiver-backup.json \
    --iam-account="$SA@$PROJECT.iam.gserviceaccount.com"
```

**2. Host.** The key, read only by systemd; the user, before any deploy that carries the
unit, since `deploy.sh` refuses a `User=` this host cannot resolve ([DEPLOYMENT.md § The service user](DEPLOYMENT.md#the-service-user-archiver339)).

```bash
sudo install -m 0400 -o root -g root co-archiver-backup.json /etc/archiver/co-archiver-backup.json
sudo useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin archiver_backup
```

**3. Postgres**, once per cluster (a role is cluster state, which no dump carries). The
report must read `t` for `login`, `inherit`, `no_password`, `reads_all_data`,
`can_connect`, `f` for the rest, and three zeros:

```bash
sudo -u postgres psql -d archiver < scripts/setup-backup-role.sql
```

**4. co-status**: a request on CannObserv/status for monitor `co-archiver-backup` in tenant
`co-archiver`. The tenant's key is already `/etc/archiver/status-checkin.key`: no new key.

| Field | Value | Why |
|---|---|---|
| `interval_seconds` | `86400` | one run a night |
| `grace_seconds` | `7200` | the 10 min jitter plus the unit's 1 h timeout: a run killed by it cannot check in |
| `renotify_seconds` | `86400` | every failed night still reports; the next `ok` sends "has cleared" (status#28) |
| `title_template` / `body_template` | `archiver backup {{ outcome }} on {{ source_host }}` / `{{ error }}` | rendered for an `alert` |

Its id goes into the unit as `Environment=CO_ARCHIVER_BACKUP_MONITOR_ID=<ULID>`, by PR and
deploy, as drift's did. Then the status#17-style alarm rehearsal after the first `ok`.

## Turning it on (once)

After the deploy that ships #233 (it installs both units and prints the enable hint):

```bash
sudo systemctl start archiver-backup.service             # one run, by hand
journalctl -u archiver-backup -n 5 -o cat                 # "Backup uploaded gs://co-gcs-archiver-backup/co-registrar/<ts>.dump"
sudo systemctl enable --now archiver-backup.timer         # only once the run above succeeded
systemctl list-timers archiver-backup.timer               # next run about 03:17 UTC
```

`243/CREDENTIALS` is the GCS key missing; `FATAL: role "archiver_backup" does not exist`
is step 3 not run; `permission denied for database` is its `CONNECT`.

**Prove the grant is create-only**, on a probe object of its own: the overwrite and the
delete must both answer **403**. A success means the identity could erase its own history.
(A create over an existing name proves nothing: GCS answers `if_generation_match=0` with
412 whatever the grant.) As root, the one identity that reads the key file:

```bash
cd /srv/archiver/live && sudo env PYTHONDONTWRITEBYTECODE=1 \
  GOOGLE_APPLICATION_CREDENTIALS=/etc/archiver/co-archiver-backup.json .venv/bin/python - <<'PY'
from datetime import UTC, datetime
from google.api_core.exceptions import Forbidden
from google.cloud import storage
blob = storage.Client().bucket("co-gcs-archiver-backup").blob(f"probe/{datetime.now(UTC):%Y%m%dT%H%M%SZ}")
blob.upload_from_string(b"probe", if_generation_match=0)  # the create: must succeed
for attempt, act in (("overwrite", lambda: blob.upload_from_string(b"again")), ("delete", blob.delete)):
    try:
        act(); print(f"{attempt}: ALLOWED, the grant is too wide")
    except Forbidden:
        print(f"{attempt}: 403, create-only holds")
PY
```

The probe has no `.dump` suffix, so no listing shows it; the lifecycle rule removes it.

## Restore

Run by hand, as root (it reads the key file itself), from the live release. **Name the
source host**: `--latest` requires `--prefix`, because a replacement host's own timer
writes under its own name, and its newest dump is a real, verifiable dump of the wrong
database.

```bash
cd /srv/archiver/live
R='sudo env PYTHONDONTWRITEBYTECODE=1 ARCHIVER_BACKUP_BUCKET=co-gcs-archiver-backup GOOGLE_APPLICATION_CREDENTIALS=/etc/archiver/co-archiver-backup.json .venv/bin/python -m src.core.restore'
$R --list                                                           # every host's dumps
$R --latest --prefix co-registrar --download-only /root/archiver-restore   # fetch, sha256, verify
```

**`--into` refuses** a database without a `_test`/`_dev` suffix unless
`--allow-production` is given, and any database that already holds a schema or a relation,
whatever the flag: never `--clean`, one transaction, so a failure leaves it empty.

**The drill** (and acceptance check 6): into a scratch database, compared with production.

```bash
sudo -u postgres createdb archiver_restore_test
$R --latest --prefix co-registrar --into archiver_restore_test --run-as postgres
for db in archiver archiver_restore_test; do
  sudo -u postgres psql -At -d "$db" -c "SELECT (SELECT version_num FROM information.alembic_version),
    (SELECT count(*) FROM information.info_items), (SELECT count(*) FROM information.app_users)"
done                                  # equal, give or take writes since the dump
sudo -u postgres dropdb archiver_restore_test   # it holds the personal data: don't keep it
```

**Into production** (a lost or replaced database). The dump carries owners and grants but
not the roles, nor the database's `CONNECT` grants, so on a fresh cluster first: role
`archiver` with the password `/etc/archiver/.env` already holds
([plans/2026-10-10-339-service-user-cutover.md](plans/2026-10-10-339-service-user-cutover.md)),
role `exedev` ([plans/2026-10-11-348-prod-read-access.md](plans/2026-10-11-348-prod-read-access.md)),
then:

```bash
sudo systemctl stop archiver.service
sudo -u postgres createdb -O archiver archiver
sudo -u postgres psql -qv ON_ERROR_STOP=1 -d archiver \
  -c 'REVOKE CONNECT, TEMPORARY ON DATABASE archiver FROM PUBLIC' \
  -c 'GRANT CONNECT ON DATABASE archiver TO archiver, exedev'
$R --latest --prefix co-registrar --into archiver --allow-production --run-as postgres
cd /home/exedev/archiver && uv run python -m src.core.reader_grants --sql --database archiver |
  sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d archiver -c 'SET ROLE archiver' -f -
sudo -u postgres psql -d archiver < scripts/setup-backup-role.sql
sudo systemctl start archiver.service && curl -s localhost:8000/health
```

Then check `alembic_version` against the dump's `alembic_head` (`--list` shows it) and the
row counts against the last known; a database behind the release's head is migrated by the
next `scripts/deploy.sh`.

## When it alerts

| Fault | Remedy |
|---|---|
| `failed` | the `error` says which step: `bucket … not found` (the bucket, or the SA's `objectViewer`); `pg_dump exited` (a lock it would not wait for, after a deploy: rerun by hand); `already exists with different contents` (two runs in one second); a google.auth error (the key revoked or rotated) |
| `misconfigured` | the unit was edited or overridden: `ARCHIVER_BACKUP_BUCKET` unset, or `GOOGLE_APPLICATION_CREDENTIALS` set outside the unit's own line |
| `missing` | no run checked in: `systemctl status archiver-backup.timer`, `journalctl -u archiver-backup`; a failed start (`243/CREDENTIALS`) sends nothing |
