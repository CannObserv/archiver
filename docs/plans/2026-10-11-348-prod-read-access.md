# archiver#348 - read-only production access for agents

The boundary this sets up, and how to use it:
[DEPLOYMENT.md § Reading production](../DEPLOYMENT.md#reading-production-archiver348).
This file holds the decision record and the steps that run once per VM.

## Decision

**Option A: a peer-authenticated role named `exedev`.** It connects only over the Unix
socket (`local all all peer`), so the OS user `exedev` logs in as role `exedev`. It has no
password, so TCP (`scram-sha-256`) is closed to it. It is read-only because it has
`SELECT` and nothing else. Rejected:
- B (password role): adds a secret that every `exedev` process can read anyway.
- C (sudo wrapper): starts as superuser, and `RESET ROLE` undoes the restriction.
- D (API key): keys have no scope, and it misses the outbox and bus tables.
- E (snapshot): stale by construction. Still possible later, as an addition.

| | Decision | Why |
|---|---|---|
| (a) | `app_users`/`api_keys` **by column** | `app_users`: `id, created_at, updated_at`. `api_keys`: `id, user_id, label, key_prefix, created_at, last_used_at`. `email`, `external_id` and `key_hash` are withheld. A column added later starts withheld, and `tests/core/test_reader_grants.py` fails until it is classified. |
| (b) | `log_statement = 'all'` **on** | Only a superuser can change it, so unlike the timeouts it actually holds. It writes to `/var/log/postgresql/postgresql-16-main.log` (`postgres:adm 0640`), not journald. It records queries, not results. |
| (c) | **Default privileges + re-grant after each migration** | A new table is readable without a grant. `scripts/deploy.sh` re-applies `src/core/reader_grants.py` after every migration, so a restricted table that a migration recreates is whole-table readable only until the end of that deploy. |

### What the review corrected (2026-10-11, #348 comment)

1. **The role's timeouts are session defaults, like `default_transaction_read_only`.** A
   session can `SET statement_timeout = 0`. Only `CONNECTION LIMIT` and `log_statement`
   actually hold. So the lock hazard is fixed on the migration side:
   `alembic/env.py` sets `SET LOCAL lock_timeout = '5s'`. A migration blocked by any
   reader fails fast, and `deploy.sh` switches nothing. Before this, API queries queued
   behind the migration's pending `ACCESS EXCLUSIVE` lock.
2. **A table-level `SELECT` overrides column privileges.** A restricted table loses its
   table-level grant (which takes its column grants with it) and gets the column allowlist
   back.
3. **#334's question needs Python, and `db_safety` rightly refuses production.** Export
   one JSON row per line with `psql -At` (not `COPY`, whose text format escapes
   backslashes), then validate offline (below). Never set `ARCHIVER_ALLOW_PRODUCTION_DB` in
   a shell to read.

### Where each piece lives

| Piece | Who applies it | Where |
|---|---|---|
| The role, its limits, `log_statement`, `pg_read_all_stats` | superuser, once | the runbook below |
| `CONNECT`, `USAGE`, `SELECT`, default privileges, column allowlists | `archiver`, the owner, on every deploy | `src/core/reader_grants.py`, run by `scripts/deploy.sh` on `archiver_dev` and then `archiver` |
| The host contract | `exedev`, over the socket | `tests/deploy/test_prod_reader.py` (skips without the role) |

## Runbook (once per VM, operator-present, after the PR merges)

Each step can be undone before the next.

**1. The role.** Before step 2 it can't connect to `archiver`, which grants `CONNECT` to
its owner alone. It can connect to `archiver_dev`, `archiver_test` and `postgres`, which
keep the default `PUBLIC` `CONNECT`, and every deploy's rehearsal grants it the same reads
on `archiver_dev`. That's harmless: agents already own both databases as `archiver_agent`.

```bash
sudo -u postgres psql -X -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE exedev LOGIN CONNECTION LIMIT 3;  -- no PASSWORD: TCP is scram-sha-256, so socket only
ALTER ROLE exedev SET default_transaction_read_only = on;  -- belt and braces, not the boundary
ALTER ROLE exedev SET statement_timeout = '30s';
ALTER ROLE exedev SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE exedev SET log_statement = 'all';
GRANT pg_read_all_stats TO exedev;  -- other sessions' pg_stat_activity.query, for lock debugging
SQL
psql -X -d archiver -c 'SELECT 1'   # permission denied for database "archiver"
```

**2. The grants.** These are the statements `deploy.sh` runs as `archiver`. Here a
superuser session runs them under `SET ROLE archiver`, so the default privileges are
`archiver`'s. The next deploy applies them again on its own.

```bash
cd /home/exedev/archiver && git switch main && git pull --ff-only
uv run python -m src.core.reader_grants --sql --database archiver |
  sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d archiver -c 'SET ROLE archiver' -f -
```

**3. Prove it.** Every test passes and none skips:

```bash
set -a; . .env; set +a
uv run pytest tests/deploy/test_prod_reader.py -v
psql -X -d archiver -c 'SELECT current_user, count(*) FROM information.info_items'
grep 'exedev@archiver' /var/log/postgresql/postgresql-16-main.log | tail -3
```

**4. The next deploy** reports `granted exedev read access to archiver_dev`, then the same
for `archiver`.

### Undo

- **Suspend** (one statement): `sudo -u postgres psql -c 'ALTER ROLE exedev NOLOGIN'`.
- **Remove**: drop the role's privileges in each database that has them, then the role.
  `deploy.sh` then reports it absent and grants nothing.

  ```bash
  for db in archiver archiver_dev; do sudo -u postgres psql -X -d "$db" -c 'DROP OWNED BY exedev'; done
  sudo -u postgres psql -X -c 'DROP ROLE exedev'
  ```

## First use: #334's pre-flight

The question: does any actively assigned production RepSpec fail `validate_rep_spec`? Export
the documents over the socket, one JSON object per line, then validate them with no database at all:

```bash
out=/tmp/claude-1000/specs-334.jsonl  # or the session scratchpad
psql -X -At -d archiver -c "SELECT json_build_object('rep_spec_id', s.rep_spec_id, 'document', s.document)
  FROM information.rep_specs s WHERE EXISTS (SELECT 1 FROM information.info_item_rep_specs a
  WHERE a.rep_spec_id = s.rep_spec_id AND a.deactivated_at IS NULL)" > "$out"
uv run python - "$out" <<'PY'
import json, sys
from src.core.rep_spec_schema.validator import validate_rep_spec
for line in open(sys.argv[1]):
    row = json.loads(line)
    ok, errors = validate_rep_spec(row["document"])
    print(row["rep_spec_id"], "ok" if ok else errors)
PY
```
