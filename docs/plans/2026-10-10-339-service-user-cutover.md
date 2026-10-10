# archiver#339 - service-user cutover (once per VM)

The boundary this sets up, and why each piece exists:
[DEPLOYMENT.md § The service user](../DEPLOYMENT.md#the-service-user-archiver339).
Out of DEPLOYMENT.md because it runs once per VM, never in a routine deploy.

Operator-present, after the PR merges. Steps run in order, and each one can be undone
before the next. `sudo systemctl` is the operator's.

**1. The user.** `deploy.sh` refuses a release whose units name a user the host lacks.

```bash
sudo useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin archiver
getent passwd archiver; getent group archiver
```

**2. Deploy.** Installs the four units with `User=archiver`, restarts the API and forces a
bus-health pass.

```bash
cd /home/exedev/archiver && git switch main && git pull --ff-only && scripts/deploy.sh
systemctl show -p User --value archiver archiver-bus-health archiver-pm-org-refresh archiver-drift
ps -o user= -p "$(systemctl show -p MainPID --value archiver)"          # archiver
sudo systemctl start archiver-pm-org-refresh.service archiver-drift.service
journalctl -u archiver-pm-org-refresh -u archiver-drift -n 10 -o cat
```

**3. Close the file.** systemd keeps reading it as root. The `.env.bak-*` copies hold the
same secrets.

```bash
sudo chown root:root /etc/archiver/.env /etc/archiver/.env.bak-*
sudo chmod 600 /etc/archiver/.env /etc/archiver/.env.bak-*
sudo systemctl restart archiver && curl -s http://127.0.0.1:8000/health    # read as root
cat /etc/archiver/.env                                                     # Permission denied
```

Undo: `sudo chown root:exedev …; sudo chmod 640 …`.

**4. Prove a rollback, then come back.** Deploy the build before #339: its units run as
`exedev` with `uv run`, and still start, because systemd reads the file. Then deploy `main`
again.

```bash
scripts/deploy.sh <the build before #339>    # releases are listed in /srv/archiver/releases
scripts/deploy.sh
```

**5. The agents' role.** `exedev` keeps its password, which goes into the repo `.env` and
`dev.env`. Never use `REASSIGN OWNED`: it also reassigns the databases a role owns, so it
would hand over production's. pg_trgm stays `archiver`'s, because `ALTER EXTENSION` has no
`OWNER TO`. That matters only to a migration that drops the extension.

```bash
pw="$(openssl rand -hex 24)"
sudo -u postgres psql -qv ON_ERROR_STOP=1 <<<"CREATE ROLE archiver_agent LOGIN PASSWORD '$pw';"
for db in archiver_dev archiver_test; do
  sudo -u postgres psql -qv ON_ERROR_STOP=1 -d "$db" <<SQL
ALTER DATABASE $db OWNER TO archiver_agent;
DO \$\$ DECLARE t regclass; BEGIN
  IF to_regnamespace('information') IS NOT NULL THEN
    ALTER SCHEMA information OWNER TO archiver_agent;
    FOR t IN SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'information' AND c.relkind IN ('r', 'p')
    LOOP EXECUTE format('ALTER TABLE %s OWNER TO archiver_agent', t); END LOOP;
  END IF;
END \$\$;
SQL
  sudo -u postgres psql -Atd "$db" -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n
    ON n.oid = c.relnamespace WHERE n.nspname = 'information' AND c.relowner = 'archiver'::regrole"
done                                                                       # 0, 0
url_to_agent='s#^((TEST_DATABASE_URL|ARCHIVER_DEV_DATABASE_URL)=[^:]+://)archiver:[^@]*@#\1archiver_agent:'"$pw"'@#'
sed -E -i "$url_to_agent" /home/exedev/archiver/.env
# sed as exedev, never under sudo: sudo journals its argv, and this one holds the password.
tmp="$(umask 077 && mktemp)" && sed -E "$url_to_agent" /etc/archiver/dev.env >"$tmp" &&
  sudo install -m 640 -o root -g exedev "$tmp" /etc/archiver/dev.env; rm -f "$tmp"
unset pw url_to_agent tmp
set -a; . /home/exedev/archiver/.env; set +a; uv run pytest -q             # the suite, on archiver_agent
```

Copy the new `.env` into any live worktree. Undo: point the URLs back at `archiver`, whose
password is unchanged until step 7.

**6. Close production to everyone but its owner.**

```bash
sudo -u postgres psql -qv ON_ERROR_STOP=1 -c 'REVOKE CONNECT, TEMPORARY ON DATABASE archiver FROM PUBLIC'
set -a; . /home/exedev/archiver/.env; set +a
uv run python -c 'import asyncio, os, asyncpg; u = os.environ["TEST_DATABASE_URL"]
u = u.replace("+asyncpg", "").rsplit("/", 1)[0] + "/archiver"
asyncio.run(asyncpg.connect(u))'                                           # permission denied for database
```

Undo: `GRANT CONNECT, TEMPORARY ON DATABASE archiver TO PUBLIC`.

**7. Rotate `archiver`'s password**, which `exedev` has held. Root generates the new
password, so it never reaches an `exedev` process's argv (`/proc/*/cmdline` is
world-readable) or its shell. Python gets it in its environment and psql on stdin.
`log_statement` is `none`.

```bash
sudo bash -s <<'ROOT'
set -euo pipefail
f=/etc/archiver/.env
cp -p "$f" "$f.bak-339-$(date -u +%Y%m%dT%H%M%SZ)"
pw="$(openssl rand -hex 24)"
PW="$pw" python3 -c 'import os, re, sys
p = sys.argv[1]
s, n = re.subn(r"^(ARCHIVER_DATABASE_URL=[^:\n]+://archiver:)[^@\n]*@",
               lambda m: m.group(1) + os.environ["PW"] + "@", open(p).read(), flags=re.M)
assert n == 1, f"{n} ARCHIVER_DATABASE_URL lines for role archiver"
open(p, "w").write(s)' "$f"
printf "ALTER ROLE archiver PASSWORD '%s';\n" "$pw" | runuser -u postgres -- psql -qv ON_ERROR_STOP=1
systemctl restart archiver
ROOT
curl -s http://127.0.0.1:8000/health
sudo systemctl start archiver-bus-health.service archiver-pm-org-refresh.service
journalctl -u archiver -u archiver-bus-health -u archiver-pm-org-refresh -n 20 -o cat
```

Undo: put the `.env.bak-339-*` copy back, then restart. The role keeps its new password
until it is set again.
