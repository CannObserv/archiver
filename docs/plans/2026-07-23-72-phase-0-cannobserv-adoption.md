---
title: "Phase 0 — adopt cannobserv (co-core + co-core-aio) via the private GCS index"
date: 2026-07-23
status: executed (pending deploy-unit reinstall + first live CI run)
---

# Phase 0 — adopt cannobserv via find-links (co-core + co-core-aio)

**Tracking:** [#72](https://github.com/CannObserv/archiver/issues/72) Phase 0 (Wiring) · mechanism per [#75](https://github.com/CannObserv/archiver/issues/75) · version per [#77](https://github.com/CannObserv/archiver/issues/77)
**Strategy doc:** `docs/plans/2026-06-25-observer-cluster-integration-strategy-design.md`
**Precedent:** this is the first A/W/R service to adopt cannobserv; Watcher and Replicator follow the same shape.

## Problem

Phase 0 of the cluster-integration strategy wires archiver to the shared `cannobserv`
substrate and adopts one trivial pure util end-to-end, proving the toolchain before the
heavier phases (content-acquisition → co-core, bus contracts) land. The distribution
mechanism is settled by #75: **find-links against the private GCS index `gs://co-gcs-pypi`**,
not git-tag `tool.uv.sources`. Archiver has never pinned cannobserv by any mechanism, so this
is a clean first adoption — but a VM-reality wrinkle blocks the "as-written" #75 flow (below).

## Approach

Declare plain version floors for `co-core` and `co-core-aio` and resolve them from a synced
wheelhouse (`[tool.uv] find-links = ["./.wheelhouse"]`, `.wheelhouse/` gitignored), exactly as
#75 prescribes. Adopt `co_core.pure.util.hashing.sha256` as the Phase-0 validation util — it
returns a bare sha256 hexdigest, semantically identical to archiver's own `content_fingerprint`
path (`SourceRevision` identity is `sha256:<hex>`), so it is both trivial and on the Phase-1
trajectory (fingerprint logic moves to co-core next). A red→green test asserts co-core's `sha256`
matches archiver's existing hashing, proving the dependency is importable and correct through the
project's real install mechanism.

Pin target: **cannobserv v0.3.4** (latest tag; supersedes #77's v0.3.1) via floors
`co-core>=0.3,<0.4` and `co-core-aio>=0.3,<0.4`. Reproducibility comes from `uv.lock` (frozen
version + wheel hash), which **must be generated against the real GCS wheels** — not
locally-built wheels, whose hashes would not match and would break `uv sync --frozen` in CI/deploy.

## The blocker (#75's premise does not hold on this VM)

#75 chose find-links to *"reuse credentials the VM already has (GCS)"* and *"avoid provisioning a
GitHub credential."* Verified reality on archiver's VM is the inverse:

- **Not a GCP VM.** No metadata server, no ADC, no service-account key, no `gcloud`, no
  `google-cloud-storage`. There is **no path to the private bucket** without new provisioning.
- The only cannobserv-relevant credential present is `GH_TOKEN_CANNOBSERV` (a working GitHub
  PAT with read on the private repo) — which find-links does not use.

So the wheelhouse cannot be populated until GCS read access is provisioned **onto this exe.dev
VM** (and onto the CI runner + the deploy image). That is user-side infra work; the agent cannot
mint cloud identity. Until then, `uv sync` / `uv lock` cannot resolve `co-core`, so the lockfile
and the passing test cannot be produced. This plan therefore splits into **operator steps**
(provisioning) and **agent steps** (wiring), sequenced so the agent finishes in two commands once
the operator unblocks GCS.

## Tradeoffs / alternatives

- **git-tag `tool.uv.sources` via the existing PAT** — rejected by operator decision (2026-07-23)
  in favor of honoring #75. Would work today with zero new infra (verified: `co-core@v0.3.4`
  installs from the git subdirectory, builds from source in ~6s), and matches strategy-doc
  Distribution decision #4. Kept here as the documented fallback if GCS provisioning proves
  impractical on exe.dev.
- **co-core only (drop co-core-aio in Phase 0)** — rejected: strategy doc wants Phase 0 to
  "surface co-core-aio maturity gaps early," and Phase 1 (fetchers → co-core-aio) needs it
  regardless. co-core-aio adds only `httpx` (already a direct dep).
- **Vendor/commit the wheels** — rejected: defeats find-links and #75's gitignore-the-wheelhouse
  model; `uv.lock` is the reproducibility anchor, not the wheelhouse contents.

## Steps

**Operator (unblocks find-links — agent cannot perform):**

1. Grant a GCP identity `roles/storage.objectViewer` on `gs://co-gcs-pypi`, and make that identity
   usable from **(a) this VM, (b) the CI runner, (c) the deploy image**. On a non-GCP host
   (exe.dev), the simplest form is a service-account JSON key referenced by
   `GOOGLE_APPLICATION_CREDENTIALS`; document whichever mechanism is chosen.
2. Install the sync tool on each environment: either the Cloud SDK (`gcloud storage`) or the
   `google-cloud-storage` Python lib for a keyless rsync helper. Confirm
   `gcloud storage ls gs://co-gcs-pypi/wheels/` (or equivalent) succeeds on the VM.

**Agent (wiring — ready to land once step 1–2 done):**

3. `pyproject.toml`: add `co-core>=0.3,<0.4` and `co-core-aio>=0.3,<0.4` to `[project.dependencies]`;
   add `[tool.uv] find-links = ["./.wheelhouse"]` (leaving `[tool.uv.sources]` for the vendored
   clients untouched — no git entries for cannobserv). Add `.wheelhouse/` to `.gitignore`.
4. Wire the wheelhouse-sync step (`gcloud storage rsync -r gs://co-gcs-pypi/wheels ./.wheelhouse`)
   into: local dev (document in CLAUDE.md), the CI `test`/`lint`/`client-drift` jobs (before
   `uv sync`), and `deploy/` (before the service installs deps). Each uses that environment's GCS
   identity.
5. Populate `./.wheelhouse` (real GCS wheels), run `uv sync`, `uv lock`; commit `uv.lock`.
6. TDD the util adoption: `tests/core/test_cannobserv_smoke.py` asserting
   `co_core.pure.util.hashing.sha256(b"...")` equals archiver's existing sha256 hexdigest for the
   same bytes. Red first (before the dep resolves), then green.
7. Update docs: CHANGELOG.md is **not** required (no contract-visible path touched — pyproject,
   CI, deploy, tests, docs only). Update CLAUDE.md ("Environment & Tooling" + a new dependency note)
   with the wheelhouse-sync step and the co-core dependency, so Watcher/Replicator inherit the
   precedent. Note in #75/#77 that archiver adopted v0.3.4 via find-links and record the
   exe.dev-not-GCP wrinkle for W/R.

## Execution notes (2026-07-24)

- **Credential reality resolved the CI mechanism to WIF, not an SA-key secret.** The VM
  is not GCP-hosted, so it carries the `co-pypi-reader@co-gcs` SA **key** at
  `GOOGLE_APPLICATION_CREDENTIALS` (in `/etc/archiver/.env`). CI instead authenticates
  **keyless** via Workload Identity Federation.
- **The publish provider was not widened.** Its condition
  (`repository == 'CannObserv/cannobserv' && ref startsWith refs/tags/v`) also guards the
  write-capable publish SA; loosening it would let cannobserv non-tag runs impersonate that
  SA. Instead a **second, read-scoped provider** `github-ci`
  (`repository_owner == 'CannObserv'`) was added to the same `github` pool, the org-scoped
  `GCP_WIF_PROVIDER` var (Archiver+Watcher) points at it, and `co-pypi-reader` grants
  `workloadIdentityUser` to `attribute.repository/CannObserv/archiver`. Watcher inherits this
  verbatim; add its principalSet binding when it adopts.
- **Only `lint` + `test` got the auth+sync steps.** `client-drift` runs only `--no-project`
  scripts and never resolves co-core, so it needs no GCS access.
- **Deploy: reinstall is a manual step, not done during execution.** The live 8020 service
  runs from this same checkout; the unit gained a non-fatal `ExecStartPre` wheelhouse sync.
  The unit was **not** reinstalled and the service **not** restarted here — that is the
  post-merge deploy action (`deploy/README.md`).
- **Version:** adopted **v0.3.4** (latest), superseding #77's v0.3.1.

## Open questions / risks

- **GCS access on exe.dev is the gating risk.** exe.dev VMs are not GCP-hosted, so there is no
  ambient identity — a real SA key (or WIF) must be placed on VM + CI + deploy. If that proves
  impractical, the git-tag fallback (via `GH_TOKEN_CANNOBSERV`, already present) is the escape
  hatch and should be re-decided explicitly rather than drifted into.
- **Lockfile soundness:** `uv.lock` must be generated against GCS wheels, not locally-built ones
  (hash mismatch would break `uv sync --frozen`). Step 5 must run on an environment that can reach
  the bucket.
- **CI/deploy credential:** find-links needs a GCS credential in the CI runner and deploy image too
  — not just the VM. Confirm all three before merging (a green local run does not prove CI green).
- **`list_all` truncation (#77):** the v0.3.x pagination fix affects consumers that call `list_all`.
  Archiver has **no** cannobserv call sites yet (Phase 0 adopts only a pure util), so there is
  nothing to audit now; revisit when a paginated co/v1 or wp/v2 client is actually used.
