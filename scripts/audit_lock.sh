#!/usr/bin/env bash
# Audit both tracked locks against OSV and report what it finds. Never fail (#420).
#
# Run by .github/workflows/audit.yml and by hand. Ported from CannObserv/broker#86.
# Four audits, each reported under its own title: uv.lock and clients/python/uv.lock,
# each as runtime (--no-dev) and dev (--only-dev). Apart, so a standing dev
# advisory (virtualenv, the SDK generator) never masks a new runtime one. The dev
# closure shares packages with runtime (httpx, anyio, idna), so a finding in one
# of those shows under both titles; the runtime title is the signal.
#
# Report-only on purpose: a gate that failed on a finding would turn main red on
# someone else's disclosure date. So every exit is 0:
#   uv exit 1 (findings)        -> warning "<lock> <group> advisories"
#   any other non-zero exit     -> warning "<lock> <group> audit did not run", never clean
# Each audit's text goes to the job summary. In Actions the stdout copy sits
# between stop-commands and a random resume token: it is OSV's text, and a line
# of it starting `::` would otherwise be read as a workflow command.
#
# --frozen reads each lock as committed. A relock would need the private
# wheelhouse (CLAUDE.md, Environment & Tooling), which this job has no
# credential to fetch. `uv audit` is a preview command, hence the flag. uv
# before 0.11.19 (astral-sh/uv#19645) has the command but not the name
# `audit-command`, and rejects it with exit 2 and "Unknown feature flag", so
# that one rejection retries without the flag. From 0.11.20 (astral-sh/uv#19669)
# an unknown name only warns, so a later uv that drops the name still audits.
# tests/scripts/test_audit_lock.py pins all of it.
set -u

cd "$(dirname "$0")/.."

# <label>|<lock directory>|<group flag>
AUDITS=(
	"uv.lock runtime|.|--no-dev"
	"uv.lock dev|.|--only-dev"
	"clients/python/uv.lock runtime|clients/python|--no-dev"
	"clients/python/uv.lock dev|clients/python|--only-dev"
)

audit() { # <directory> <group flag>; sets out and rc
	out=$(uv --directory "$1" audit --frozen "$2" --preview-features audit-command 2>&1)
	rc=$?
	if [ "$rc" -eq 2 ] && [[ $out == *"Unknown feature flag"* ]]; then
		out=$(uv --directory "$1" audit --frozen "$2" 2>&1)
		rc=$?
	fi
}

for entry in "${AUDITS[@]}"; do
	IFS='|' read -r label dir group <<<"$entry"
	audit "$dir" "$group"

	if [ -n "${GITHUB_ACTIONS:-}" ]; then
		token=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
		echo "::stop-commands::$token"
		printf '%s\n' "$out"
		echo "::$token::"
		printf '### %s: uv audit --frozen %s (exit %s)\n\n```\n%s\n```\n\n' \
			"$label" "$group" "$rc" "$out" >>"${GITHUB_STEP_SUMMARY:-/dev/null}"
	else
		printf '== %s (exit %s)\n%s\n' "$label" "$rc" "$out"
	fi

	case $rc in
	0) ;;
	1)
		if [ "$dir" = . ]; then
			fix="Sync the wheelhouse, then uv lock --upgrade-package <name> (CLAUDE.md, Environment & Tooling)."
		else
			fix="In $dir: uv lock --upgrade-package <name> (no wheelhouse needed)."
		fi
		echo "::warning title=$label advisories::uv audit found advisories in $label; the job summary lists them. $fix"
		;;
	*) echo "::warning title=$label audit did not run::uv audit exited $rc; $label was not audited. The job summary has its output." ;;
	esac
done
exit 0
