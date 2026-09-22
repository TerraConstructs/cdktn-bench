# Vendored `terraform-aws-modules` for the `hcl_modules` arm

The arm's module registry is offline: a CLI-config `host` override points
`modules.v1` at a responder sidecar that serves bytes committed in this repo
(`docs/design/tf-module-registry-loopback.md`, DECISIONS.md Amendment 46 (a)/(b)).
No module byte is fetched at image build time, so the host gates and the
container grade the same tree by construction.

## What is vendored

`arms/hcl-modules/environment/modules/` — 21 `module@version` entries across 19
module names, 590 files, 4.2 MB on disk, every tree Apache-2.0 with its
`LICENSE` retained. The pruned-away part is `examples/ tests/ wrappers/ docs/
.github/ *.md *.png` at any depth, which is what takes 17 MB to 4.2 and keeps
every module's working `examples/` out of the agent's reach.

Two entries are transitive, not chosen: `kms` ships at **4.0.0** as well as
4.2.2 because `eks` and `route53` each pin exactly 4.0.0, and `acm` ships at
**6.2.0** as well as 6.3.1 because `apigateway-v2`'s `main.tf` calls it
unconditionally — no `count`, no `for_each`, invisible unless `main.tf` is read
past `variables.tf`. Four entries (`alb`, `sqs`, `rds`, `eks`) are decoys: no
spec needs them, and module and version selection are only measured skills if a
wrong answer is reachable. **Which four is recorded only in
`scripts/vendor_modules.pins.json`**, a host-side input that reaches no build
context.

`manifest.json` records, per module: registry source, version, directory,
upstream repo, tag, commit sha, and the sha256 of every file in the pruned tree.
It carries **no prose and no bench judgement** — the responder answers
`/v1/modules/search` out of it and the file is readable in the agent container,
so a "why this module is here" field would hand the agent a scenario's reserved
vocabulary and a `decoy` flag would hand it the selection answer outright.
`generator/tests/test_vendored_modules.py` sweeps the file with every spec's own
deny list, and one companion test there fails on the literal word `decoy`.

The pin is the upstream **commit sha** plus those per-file hashes, never an
archive digest: codeload's `refs/tags/vX` and `<sha>` tarballs of one identical
tree have different gzip bytes.

## How to refresh

The owner runs this on a version bump; it is not part of any build.

```
python3 scripts/vendor_modules.py --check-upstream   # tags still at pinned shas?
$EDITOR scripts/vendor_modules.pins.json             # bump version + tag + sha
python3 scripts/vendor_modules.py                    # fetch, prune, rewrite manifest
python3 scripts/vendor_modules.py --verify
env -u NODE_OPTIONS uv run pytest generator/tests/test_vendored_modules.py
```

`--check-upstream` resolves each pinned tag through the GitHub API and reports
disagreement without writing anything; it reads `GH_TOKEN`/`GITHUB_TOKEN` from
the environment when present, because 21 anonymous lookups can exhaust the
60-per-hour unauthenticated limit. The fetch mode replaces each tree rather
than overwriting into it, so a file the new version deleted cannot survive as
an extra that `--verify` would then flag.

A bump must re-check the two floors the decoys carry — `eks` constrains
`hashicorp/aws >= 6.59`, `rds` constrains `terraform >= 1.11.1`, both satisfied
by the arm image's 6.66.0 / 1.15.8 (Amendment 48). The constraint test reads
that pair out of `arms/hcl-raw/environment/Dockerfile` rather than restating it.

## The build-time contract

The image COPYs the tree to `/opt/terraform-modules` and then runs

```
python3 scripts/vendor_modules.py --verify --root /opt/terraform-modules
```

which must exit 0 for the build to proceed. `--verify` needs nothing but the
`--root` directory and its own `manifest.json`: no pin file, no network, Python
stdlib only, on the `python3` the arm image already installs. It fails on a
changed byte, a missing file, an unlisted file and an unnamed directory — each
proven by mutation, and proven offline under `docker run --network none`.

## What the manifest does *not* protect

The agent container runs as **root** (no arm Dockerfile declares a `USER`), so
Amendment 46 (c)'s first half — "the tree is unreadable to the agent user" — is
void as written: file modes hide nothing from uid 0. What the tree therefore has
to be safe to read is a property of its CONTENT, which is why the manifest
carries no decoy flag and the module bytes are upstream's own, byte-for-byte.

The half that carries (c) is the verifier deny landing in phase 5, and its
wording in Amendment 46 is too broad to implement as written: a registry module
calls its own submodules by relative path, so `ecs`, `eks` and `rds` each
install `.terraform/modules/modules.json` entries whose `Source` is
`./modules/...`. The rule that is both true and sufficient is scoped to the
calls the ROOT module makes — an entry whose `Key` contains no dot — because
those are the only ones the agent wrote. `arms/hcl-modules/environment/preflight.sh`
asserts it in that form against a fixture that installs three relative-source
entries, so composing against `/opt/terraform-modules` directly still scores
nothing while a legitimate module is not refused for its own internals.

Making the first half real would take either a non-root agent user in the arm
image or keeping `manifest.json` out of the agent image and in the sidecar only
— an owner call, not a phase-4 one.
