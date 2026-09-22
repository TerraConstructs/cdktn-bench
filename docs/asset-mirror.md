# Build-time asset mirror

Every arm image downloads the same six pinned assets at build time — opa, jq,
hcl2json, the cfn-guard tarball, the terraform zip and the AWS CLI zip. A task
image embeds its arm's Dockerfile verbatim, so it refetches all of them on a
cold build. When a network cannot pull a 57 MB GitHub release asset reliably,
that turns every task build into a coin flip, and Harbor voids a trial whose
compose build exceeds `build_timeout_sec`, 600 seconds by default.

`scripts/asset_mirror.py` keeps those assets on the host and serves them over
HTTP to the build containers.

**One cache key.** `ARG ASSET_MIRROR` defaults to the fixed URL
`http://host.lima.internal:8899` and nothing overrides it, so every build of a
given Dockerfile — `make build-arms`, `scripts/prebuild-tasks.sh`, and the
no-build-arg `docker compose build` Harbor runs — hashes the same `RUN`
strings and shares one layer cache. Each fetch probes the mirror
(`curl -fsI --connect-timeout 2 --max-time 5 "$ASSET_MIRROR/<basename>"`) and
uses it only when it answers; otherwise it fetches the upstream URL. A build
with no mirror running is therefore correct, just slow.

**The pins are the integrity guarantee; the mirror is only a source.** Each
Dockerfile fetch still runs the `sha256sum -c` hardcoded next to it, so a
mirrored file that does not match the pin fails the build exactly as a
corrupted download does. The AWS CLI zip is unversioned upstream and therefore
unpinned in the Dockerfile too — the mirror records the sha it observed in
`assets/manifest.json` as information, and nothing enforces it.

## Where the asset list comes from

The Dockerfiles are the single source of truth. `asset_mirror.py` parses each
`arms/*/environment/Dockerfile` for every pinned fetch — URL, per-arch sha256,
the path curl writes to — so the mirror can never drift from a pin.
`assets/manifest.json` is a written snapshot of that derivation, refreshed by
`populate` and by `manifest --write`; `test/test_asset_mirror.py` fails if a
Dockerfile pin is missing from it, if an arm's `ASSET_MIRROR` default drifts
from the fixed URL, or if a fetch does not probe the mirror and fall back to
its upstream URL.

**What the derivation cannot see is a build step that is not a `curl`.** Both
Terraform arms pre-warm a provider `filesystem_mirror` with `terraform providers
mirror`, which fetches from `releases.hashicorp.com` on its own and so is outside
this mirror entirely. `arms/hcl-raw` pays that for one provider; `arms/hcl-modules`
pays it for the eight its vendored module tree declares, measured at ~45s against
Harbor's 600s cold-build timeout. A ninth would need that headroom argued rather
than assumed — `arms/hcl-modules/README.md` records why `kreuzwerker/docker`, at
370s on its own, is excluded.

## Populate, serve, build

```bash
# Fill ~/.cdktn-bench/assets (override with $CDKTN_ASSET_DIR). --from-images
# recovers the three bare binaries out of already-built cdktn-bench/<arm>:dev
# images instead of downloading them; archives have no counterpart inside an
# image and are always fetched upstream. Only sha-verified files are kept.
python3 scripts/asset_mirror.py populate --from-images

python3 scripts/asset_mirror.py verify     # re-hash everything
python3 scripts/asset_mirror.py manifest   # print the derived asset list

# Serve it to build containers on the port the Dockerfiles probe. colima
# publishes the macOS host inside a container as host.lima.internal.
python3 scripts/asset_mirror.py serve --port 8899

# Or let the build bring it up and take it down again:
make build-arms
```

`scripts/asset-mirror-up.sh` is the one place that starts the server:
`make build-arms`, `scripts/prebuild-tasks.sh` and `scripts/run-bench.sh` all
call it, it leaves an already-listening server alone, and it prints the PID of
one it started so the caller can stop it. `run-bench.sh` holds it for the whole
run, not just the prebuild — Harbor builds a task image itself on any cache
miss, and that build probes the same port.

`$CDKTN_ASSET_MIRROR_URL` is an escape hatch for a docker host where
`host.lima.internal` does not resolve. Setting it passes `--build-arg
ASSET_MIRROR=...`, which **forks the layer cache away from Harbor's
no-build-arg build** — the prebuild then warms nothing Harbor reuses. Leave it
unset unless the default host is wrong.

## Task images

`scripts/prebuild-tasks.sh <task-dir-basename> …` builds task images serially,
bringing the mirror up first and stopping it again unless one was already
listening. The images are tagged
`cdktn-bench-prebuild/<task>:dev`; the tag exists only to keep the warmed
layers referenced. What actually matters is the local layer cache: Harbor's
later compose build of the same Dockerfile and context hits it instead of
refetching.

`scripts/run-bench.sh` does this automatically for every task named with
`--include-task-name`/`-i` before it invokes the runner. `--no-prebuild` (or
`CDKTN_PREBUILD=0`) skips it. A run that names no tasks prebuilds nothing —
building the whole dataset costs more than it saves.

## What the prebuild covers

Harbor builds a task with `docker compose --project-name <session>
--project-directory <task>/environment -f docker-compose-build.yaml build` and
passes no build args. Because the Dockerfile's `ASSET_MIRROR` default is the
only value anyone ever builds with, that build hashes the same `RUN` strings as
the prebuild and every layer is `CACHED`, pinned fetches included. Reproduce it
against a prebuilt task:

```bash
env CONTEXT_DIR="$PWD/tasks/anchor/ecs-swappiness-hcl-raw/environment" \
  docker compose --project-name cachecheck \
    --project-directory "$PWD/tasks/anchor/ecs-swappiness-hcl-raw/environment" \
    -f .venv/lib/python3.13/site-packages/harbor/environments/docker/docker-compose-build.yaml \
    build
```

The gap that remains is a task whose image was never prebuilt: Harbor builds it
cold, and the probe is what keeps that cheap — it hits the mirror instead of
GitHub as long as `run-bench.sh`'s server is up.

## Bumping a pin

Edit the Dockerfile as before. Then re-run `populate`, which picks up the new
URL and sha automatically and refetches anything whose local copy no longer
matches. Changing an arm Dockerfile moves the equipping hash: rebuild the arm
images and re-run `env setup` before the next live run.
