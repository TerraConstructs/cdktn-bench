# `equipping/` — the tuned material of the `arm x equipping` factorial

Prereg §2.2's tuned column, ROADMAP M2. Equipping is a **run dimension**, not a
scenario property: the same prompt, image, oracle and shard, with different
skills and MCP servers bolted on. So the material lives here once for the whole
corpus, and a spec only **opts in** (`equipping.levels`, specs/SCHEMA.md) to
having tuned tasks emitted for it.

```
MANIFEST.json                     per-file sha256 + pins; `vendor_equipping.py --verify`
vendor/<pkg>-<version>/           upstream skills, verbatim, LICENSE beside them
bench/<skill>/                    bench-written skills (an upstream that cannot be redistributed)
bench/<skill>.UPSTREAM.md         what a bench-written skill stands in for -- outside every skill dir
levels/<arm-dirname>.<level>.yaml which skills and MCP servers one (arm, level) declares
```

`scripts/vendor_equipping.pins.json` holds the pins **and the reasoning**; it
ships in no image. `MANIFEST.json` holds names, versions and digests only.

## The three levels

`bare` is what the corpus emits today — unchanged bytes, unchanged task dir
names, unchanged `equipping_hash`. `tuned` is prereg §2.2's row. `tuned-stale`
is ROADMAP M2's H2, the staleness cost: the **same** material at a pin whose
version-specific facts no longer hold, identical to `tuned` in the skill
directory name, the frontmatter `name` and the MCP server list, so nothing in
the container reveals which level a trial drew.

## How a level reaches the trial, and the hash

`generator/equipping.py::materialize` writes the level into the task's
`environment/equipping/`; the generator appends one `COPY equipping/
/opt/equipping/` to that task's Dockerfile, outside `/app/project` because this
is equipping and not part of the graded artifact. `task.toml [environment]`
then carries `skills_dir = "/opt/equipping/skills"` and one
`[[environment.mcp_servers]]` per server — the two channels Harbor actually
reads (`harbor/agents/installed/claude_code.py` copies `skills_dir` into
`$CLAUDE_CONFIG_DIR/skills/` and writes `mcpServers` into `.claude.json`).

Four independent places therefore move between `bare`, `tuned` and
`tuned-stale`, and `gates/equipping.py` (scheme 2, DECISIONS.md Amendment 47)
hashes all four: the copied `skills/` tree, the emitted `mcp.json`,
`[environment] skills_dir`, and `[environment] mcp_servers`.

The hash proves the **declaration** moved. It cannot prove the material
**arrived**, and Harbor makes both ways of not arriving silent: skills are
installed with `cp -r <skills_dir>/* ... || true`, and claude-code reports an MCP
server it cannot start in its own log and carries on. So the declaration is
checked against the artifact instead — `gates/tuned_equipping.py`, `make
equipping-check` (bytes only, in `make check`) and `make equipping-preflight`
(one `docker run` per declared `stdio` command). **That gate is RED today**: no
arm image installs `awslabs.aws-documentation-mcp-server` or
`awslabs.aws-iac-mcp-server`, so a tuned trial run now would publish a row
claiming equipping the agent did not have. Installing them in the arm images is
the phase that unblocks the first tuned trial (ROADMAP M2, DECISIONS.md
Amendment 51).

The row's own label is derived, never passed: `gates/equipping.py::
harness_for_task` reads the level off the task directory and the fact that the
task is equipped at all off the same `task.toml [environment]` channel the hash
folds in, and refuses a disagreement in either direction.

## Equipping changes the prompt surface, never the oracle

A tuned task dir differs from its bare sibling in exactly two paths — `task.toml`
and `environment/` — and in nothing else. `instruction.md`, `tests/` and
`solution/` (the reference solution and the `solution/broken/` negative fixtures)
are byte-identical, mirrored from the bare task by
`gen.py::mirror_bare_task_material` because they are hand-authored and
destructive-safe, and re-checked per level by `gates/tuned_equipping.py::
oracle_identity_defects`. Without it a new tuned dir ships the scaffolded
`solve.sh` stub that exits 1 and no negative fixtures at all.

## `hcl_raw` and the index tool

`hcl_modules` tuned = index tool + AWS Docs MCP + skill. `hcl_raw` tuned =
**AWS Docs MCP + skill only**, no index tool, for three reasons: the index tool
answers from the module manifest, and `hcl_raw` vendors no modules, so every
answer it could give on that arm is "not available in this environment"; giving
it one means standing the `tf-registry` sidecar up on `hcl_raw` too, which moves
that arm's compose file and therefore every `hcl_raw` hash, for no information;
and §2.2's symmetry principle asks for "an ecosystem docs/MCP layer plus an
authoring skill", which AWS Docs MCP plus the vendored skill satisfies. This
reads §2.2's restated note (which names the index tool for both TF arms) more
narrowly than its letter — **a finisher decision**, and the alternative is
`equipping/levels/hcl-raw.tuned.yaml` plus a sidecar on that arm.

## `terraconstructs`

No level file: prereg §2.2 names tuned material for three arms and none for the
CDKTN arm (added later, Amendment 2/46). A cell invented here would be
unregistered equipping, so the grid is left ragged and `make gen` says so out
loud for every (arm, level) it does not emit.
