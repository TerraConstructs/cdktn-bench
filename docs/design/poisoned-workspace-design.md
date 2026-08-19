# Poisoned-workspace generation — design investigation (task #15)

Status: **design memo, nothing implemented.** Read-only investigation against
the tree at 2026-08-20. Requirements source: `docs/scenario-grades/2026-08-20-summary.md`
lines 39–50 (the "Poisoned workspace" bucket) and the "Immediate implications"
item 2. Companion memo: `docs/design/multistep-trial-investigation.md`
(the other new capability; §8 below covers composition).

Everything here is a proposal. Adoption needs the full
`docs/adding-scenarios.md` procedure plus a `DECISIONS.md` amendment, because
it changes what a generated task's starting workspace *is* — a
pre-registration-relevant fact.

---

## 0. TL;DR for the operator

1. **Ship the poison as `entry_file` content, not as extra files.** That is the
   only workspace path that reliably reaches the agent container today
   (§3.1) — and it is also what brownfield actually wants.
2. **There is a live bug blocking anything else:** `seeded_files` (SCHEMA §2.5)
   are written into `environment/<workspace>/…` but **no arm Dockerfile COPYs
   them**, so they exist on the host and are *absent* inside the agent
   container. `apigw-openapi` is affected today. Fix before, or as part of,
   this feature (§3.1, §9-B1).
3. **The three seeds are hand-authored per arm**, exactly like
   `solution/solve.sh` and `generator/tests/fixtures/<id>/<arm>/<entry_file>`.
   Derivation is not available: `docs/scenario-candidates.md:174` records that
   **no public AWS CDK→TF synthesizer exists**.
4. **Seed parity is proved by a new `seed_asserts` block** evaluated against
   each arm's *pre-agent* synth/plan artifact, reusing
   `generator/check_reference_paths.py`'s existing "run the real toolchain,
   resolve declared paths through the same jq compiler `static_tiers.sh` uses"
   machinery. Resource-count parity is explicitly **not** the criterion.
5. **The idempotence oracle is a live tier**, not a static one. Offline, with
   no state, `terraform plan -detailed-exitcode` is always `2`. Recommended
   shape: gating, fail-closed, modelled byte-for-byte on
   `verifier.live_check.gating` (SCHEMA §5).
6. **`lambda-alias-tracks-unpublished-latest` (pre-deployed state) should be
   deferred to multi-step `pre_invoke`**, not solved with seeded
   `terraform.tfstate` (which is TF-arms-only and therefore breaks three-arm
   parity at the arm the scenario most needs to measure).

---

## 1. Capability definition

A **poisoned workspace** (brownfield task) is a generated task whose starting
workspace is *not* the empty `entry_file` skeleton (SCHEMA §2.4's
"empty-harness" convention, `generator/gen.py:284/344/501`) but a **working,
green, semantically-equivalent-across-arms IaC configuration that already
carries a latent pitfall**.

Defining properties:

| Property | Greenfield (today) | Brownfield (this feature) |
|---|---|---|
| Starting `entry_file` | empty skeleton + `TODO(agent)` | working config with a latent pitfall |
| Starting state | synth/plan-green but resource-free | synth/plan-**green with resources** |
| Prompt | "create X" imperative | change request **or** observed incident symptom |
| Agent's job | author from scratch | modify existing config |
| What is measured | tokens-to-green on greenfield | **tokens-to-green on brownfield** |
| Where the trap fires | agent's own authoring | the agent's *change* to code it did not write |

Non-properties, stated so they cannot drift:

- The prompt **never** says "find the bug", never names the pitfall, and never
  hints that the workspace is anything other than ordinary existing config
  (§7).
- The seed is **agent-writable** — it is the file the agent is being asked to
  change. This is the opposite of `seeded_files` (SCHEMA §2.5), which are
  chmod `0o444` read-only reference inputs (`generator/gen.py:619-635`).
- The seed is **not a solution hint**: it must synth/plan green, and it must
  not contain any comment, name, or structure that signposts the trap.

Target scenarios from the graded set (`docs/scenario-grades/2026-08-20-summary.md:43-47`):

| Scenario | Needs | Single-step? |
|---|---|---|
| `named-resource-replacement-create-before-destroy` | seed + live apply×2 by the agent | yes (agent-deploys) |
| `policy-json-string-normalization-diff` | seed + **verifier-side** second `plan -detailed-exitcode` | yes, no re-prompt |
| `s3-acl-vs-object-ownership-log-delivery` | seed (+ plan-graph reader, candidates C4) | yes |
| `singleton-child-resource-clobber` | seed + live | yes |
| `lambda-alias-tracks-unpublished-latest` | seed **+ pre-deployed AWS state** | **no** — §6 |

---

## 2. Spec-schema proposal

### 2.1 Shape

A new optional top-level block, `workspace_seed`, sibling to `seeded_files`
(SCHEMA §0). Absent ⇒ today's behaviour, byte-for-byte, for every existing
spec.

```yaml
workspace_seed:
  premise: |                 # NL, arm-agnostic. Feeds instruction assembly (§7).
    …what already exists, stated as fact, never as a hint…
  entry_file:                # REQUIRED. One hand-authored seed per enabled arm.
    awscdk: |
      …TypeScript, class ScenarioStack body…
    hcl_raw: |
      …HCL resource blocks (no provider block — provider.tf owns that)…
    terraconstructs: |
      …TypeScript, class ScenarioStack extends AwsStack body…
  extra_files:               # OPTIONAL, per arm, WRITABLE (0o644). See §3.1 —
    hcl_raw: []              # blocked on the Dockerfile COPY fix.
  seed_asserts:              # REQUIRED, ≥1. The parity gate (§4). Same
    - name: …                # {op, expected, cfn_jsonpath, tf_jsonpath}
      description: …         # vocabulary as oracle.structural_asserts.
      applies_to: [awscdk, hcl_raw, terraconstructs]
      cfn_jsonpath: …
      tf_jsonpath: …
      op: exists | eq | in | contains | regex | set_eq | absent_or_eq | not_exists | not_regex
      expected: …
```

Three deliberate choices:

- **`entry_file` is a per-arm map, not a single document.** There is no
  derivation path (`docs/scenario-candidates.md:169-176`: aws-cdk-rfcs #217
  closed `not_planned`; `hashicorp/terraform-cdk` archived; no public CDK→TF
  synthesizer). Hand-authoring per arm is the *same* discipline the repo
  already applies to `solution/solve.sh` (SCHEMA §8.2 point 8) and to
  `generator/tests/fixtures/<spec-id>/<arm-dirname>/<entry_file>`
  (`generator/check_reference_paths.py` docstring, ~line 40). Reuse that
  machinery rather than inventing a second one.
- **`seed_asserts` reuses `structural_asserts`' vocabulary verbatim** —
  same `op`/`expected` table (SCHEMA §4.2), same `|fromjson` markers, same
  `generator/jsonpath_jq.py` compilation. A second, differently-behaving
  path language would be a new drift surface for zero gain.
- **`premise` is spec-level and arm-agnostic**, so it lands in the *shared*
  portion of `instruction.md` and cannot break the parity check at
  `generator/gen.py:1987-2006` / `generator/check_parity.py`.

### 2.2 Worked example — `named-resource-replacement-create-before-destroy`

> **Resource choice is illustrative and needs the standard empirical spike
> before a spec freezes** (Amendment 3's standing lesson: predicted tiers and
> provider behaviour are evidence-checked, never assumed —
> `specs/SCHEMA.md:349-354`). What is load-bearing below is the *schema shape*,
> which is resource-agnostic.

```yaml
id: named-resource-replacement-cbd
title: "Security group rename: an explicitly-named, in-use SG must be replaced"
difficulty: 2
services: [ec2]

arms:
  awscdk: true
  hcl_raw: true
  terraconstructs:
    enabled: true
    reason: >
      compute/network SecurityGroup L2 present — verify against
      arms/terraconstructs/README.md §4 at spec time.

workspace_seed:
  premise: |
    This workspace already contains the Terraform/CDK configuration for a
    small internal service: one security group and one interface VPC
    endpoint that uses it. It is deployed and healthy.

  entry_file:
    hcl_raw: |
      resource "aws_security_group" "svc" {
        name        = "internal-svc-sg"
        description = "internal service"
        vpc_id      = var.vpc_id

        ingress {
          from_port   = 443
          to_port     = 443
          protocol    = "tcp"
          cidr_blocks = ["10.0.0.0/8"]
        }
      }

      resource "aws_vpc_endpoint" "ssm" {
        vpc_id              = var.vpc_id
        service_name        = "com.amazonaws.us-east-1.ssm"
        vpc_endpoint_type   = "Interface"
        subnet_ids          = var.subnet_ids
        security_group_ids  = [aws_security_group.svc.id]
        private_dns_enabled = true
      }

    awscdk: |
      const sg = new ec2.SecurityGroup(this, "Svc", {
        vpc,
        securityGroupName: "internal-svc-sg",
        description: "internal service",
      });
      sg.addIngressRule(ec2.Peer.ipv4("10.0.0.0/8"), ec2.Port.tcp(443));

      new ec2.InterfaceVpcEndpoint(this, "Ssm", {
        vpc,
        service: ec2.InterfaceVpcEndpointAwsService.SSM,
        securityGroups: [sg],
      });

    terraconstructs: |
      …the terraconstructs L2 equivalent, same two resources, same
      explicit securityGroupName…

  seed_asserts:
    - name: sg-has-explicit-name
      description: >
        THE POISON. The security group carries an operator-chosen literal
        name on every arm — the property that makes a replacement collide.
      applies_to: [awscdk, hcl_raw, terraconstructs]
      cfn_jsonpath: "$.Resources[?(@.Type=='AWS::EC2::SecurityGroup')].Properties.GroupName"
      tf_jsonpath: "$.planned_values.root_module.resources[?(@.type=='aws_security_group')].values.name"
      op: eq
      expected: "internal-svc-sg"

    - name: sg-has-no-create-before-destroy
      description: >
        THE OTHER HALF OF THE POISON, hcl-shaped only (CFN has no
        lifecycle meta-argument; the awscdk half of this fact is
        sg-has-explicit-name above).
      applies_to: [hcl_raw, terraconstructs]
      tf_jsonpath: "$.configuration.root_module.resources[?(@.type=='aws_security_group')].lifecycle"
      op: not_exists

    - name: endpoint-consumes-the-sg
      description: >
        The SG is genuinely IN USE — the fact that turns a replacement into
        a DependencyViolation rather than a no-op. Graph-edge shaped, so it
        reads .configuration…references, never .planned_values…values
        (SCHEMA §4.2.1's plan-time-unknown rule).
      applies_to: [hcl_raw, terraconstructs]
      tf_jsonpath: "$.configuration.root_module.resources[?(@.type=='aws_vpc_endpoint')].expressions.security_group_ids.references"
      op: contains
      expected: "aws_security_group.svc"

    - name: endpoint-exists
      applies_to: [awscdk]
      cfn_jsonpath: "$.Resources[?(@.Type=='AWS::EC2::VPCEndpoint')]"
      op: exists

instruction:
  shared_body: |
    The security group in this configuration is named `internal-svc-sg`.
    Our naming convention changed: every security group must now be named
    `<team>-<service>-sg`. Rename this one to `platform-internal-svc-sg`
    and roll the change out to the account with your toolchain's real
    deploy command. The VPC endpoint that uses this security group must
    keep working throughout — it backs a service that is currently in use.
  per_arm: { … as usual … }

catches:
  - name: replacement-of-in-use-named-resource
    taxonomy: graph-dependency
    description: >
      A rename forces replacement. Terraform's default order is
      destroy-then-create; the SG is attached to a live ENI, so the destroy
      fails with DependencyViolation and the apply leaves the config
      half-applied. The correct hcl fix is BOTH
      `lifecycle { create_before_destroy = true }` AND dropping the
      explicit `name` for `name_prefix` (CBD alone collides on the literal
      name). On awscdk/terraconstructs the idiomatic L2 default (no
      explicit name) makes the collision structurally impossible.
    predicted_tier_caught:
      awscdk: "live"
      hcl: "live"
      terraconstructs_override: null
```

Note what the example does **not** do: no `applies_to` gymnastics to make the
arms look identical. `sg-has-no-create-before-destroy` is TF-shaped only,
because CFN has no `lifecycle` meta-argument — the *asymmetry is the
measurement*, and the parity discipline is about the seeded infrastructure
being the same, not about the two artifact families having the same shape.

### 2.3 Validation rules (`generator/spec_model.py`)

Add next to `SeededFile` (`generator/spec_model.py:208-232`):

1. `workspace_seed.entry_file` must have exactly one key per **enabled** arm
   (`spec.arms.enabled_arms()`), no more, no fewer. A disabled
   `terraconstructs` with a seed is a spec error, not a silent skip.
2. Every seed body must be non-empty.
3. `extra_files[].path` reuses `SeededFile`'s validators verbatim (no leading
   `/`, no `..`, not a known bootstrap filename `_KNOWN_BOOTSTRAP_FILES`) and
   additionally must not equal that arm's `output_contract.entry_file`
   (the seed already owns it).
4. `extra_files[].path` must not collide with any `seeded_files[].path` —
   one is writable, one is `0o444`; a collision would be a silent
   permission fight.
5. `seed_asserts` non-empty, `cfn_jsonpath` required iff `awscdk ∈ applies_to`,
   `tf_jsonpath` required iff a TF arm is — mirrors `structural_asserts`.
6. `premise` non-empty when `workspace_seed` is present.
7. **No-leak lint (cheap, mechanical):** reject a seed body containing any of
   `TODO`, `FIXME`, `XXX`, `HACK`, `NOTE:`, `careful`, `gotcha`, or the string
   `create_before_destroy` in a *comment* line. This is a tripwire, not a
   proof — §7 carries the real rule, which is a review-time obligation.

---

## 3. Generator change map

### 3.1 BLOCKER — the workspace seed must actually reach the container

This is the single most important finding in the memo.

`write_environment` copies `arms/<arm>/environment/` wholesale
(`generator/gen.py:660`) and then overwrites `entry_file`
(`:667-668` awscdk, `:681` hcl_raw, `:693-695` terraconstructs), then calls
`write_seeded_files` (`:703`). The task's `environment/Dockerfile` is a
**byte-identical copy** of the arm's (verified: `diff` of
`arms/hcl-raw/environment/Dockerfile` against
`tasks/anchor/apigw-openapi-hcl-raw/environment/Dockerfile` is empty; gen.py
patches only `preflight.sh`, `:673-674` and `:696-699`). And every arm's
Dockerfile COPYs **named files/dirs**, not the whole workspace:

| Arm | Dockerfile | COPY lines into `/app/project` |
|---|---|---|
| `hcl_raw` | `arms/hcl-raw/environment/Dockerfile:154-157` | `workspace/provider.tf`, `workspace/mock-sfn.py`, `workspace/main.tf` |
| `awscdk` | `arms/awscdk/environment/Dockerfile:111-118` | `workspace/package*.json`, `tsconfig.json`, `cdk.json`, `workspace/bin`, `workspace/lib` |
| `terraconstructs` | `arms/terraconstructs/environment/Dockerfile:128-147` | `app/package*.json`, `cdktf.json`, `tsconfig.json`, `app/main.ts`, `app/lib`, `app/mock-sts.js` |

Consequences:

- **A seed placed in `entry_file` works today on all three arms** —
  `workspace/main.tf`, `workspace/lib/`, `app/lib/` are each explicitly
  COPY'd. This is why §0 recommends putting the poison there.
- **`seeded_files` outside those paths never reach the container.**
  `specs/apigw-openapi.yaml:90-92` seeds `openapi/widgets-api.json`, and the
  generated tree also carries `lambda/placeholder.zip`
  (`tasks/anchor/apigw-openapi-hcl-raw/environment/workspace/{openapi,lambda}/`).
  Neither is COPY'd. That arm's own reference solution points
  `filename = "${path.module}/lambda/placeholder.zip"`
  (`tasks/anchor/apigw-openapi-hcl-raw/solution/solve.sh:50`), so a real
  in-container trial would fail `terraform validate` for a reason that has
  nothing to do with the solution.
- **Why nobody noticed:** `gates/oracle_falsifiability.py:281-320` prepares its
  sandbox by `copytree`-ing `environment/<ARM_WORKSPACE_SUBDIR[arm]>` on the
  **host** and running the toolchain there. The seeded files are present on
  that path. So `make falsifiability` / `make grading-proof` are green while
  the container is missing the files.

**Recommended fix (do this first, independent of this feature):** replace the
per-file COPY of the workspace tree with a single `COPY workspace/ ./`
(resp. `COPY app/ ./`) *after* the `npm ci` layer, keeping the existing
package.json/lockfile COPY ahead of it so the dependency layer still caches.
Then add a generator- or CI-side assertion that every file gen.py writes under
`environment/<workspace-subdir>/` is present in the built image — the cheapest
form is a `preflight.sh` step listing the expected relative paths.

Until that lands, **`workspace_seed.extra_files` must be rejected by
`spec_model.py`** rather than silently producing a task whose seed is
half-missing inside the container.

### 3.2 Change map

| File:line | Today | Change |
|---|---|---|
| `generator/spec_model.py:208-232` (`SeededFile`) | read-only reference inputs | add `WorkspaceSeed`/`SeedAssert` models next to it; add `Spec.workspace_seed: WorkspaceSeed \| None = None`; validators §2.3 |
| `generator/gen.py:284` `awscdk_stack_skeleton` | empty class body + `TODO(agent)` | when a seed exists, emit the seed body inside `ScenarioStack`'s constructor and **drop the `TODO(agent)` line and the "Empty on purpose" header** (§7) |
| `generator/gen.py:344` `hcl_raw_main_tf` | header comment + `TODO(agent)` | same: seed resource blocks; keep only the "do not create a second `provider` block / do not modify provider.tf" sentence, which is a real workspace fact, not a hint |
| `generator/gen.py:501` `terraconstructs_stack_skeleton` | empty class body | same as awscdk |
| `generator/gen.py:638-703` `write_environment` | entry_file overwrite then `write_seeded_files` | unchanged control flow; the three skeleton functions now return seed content. Add `write_workspace_seed_extra(spec, arm, workspace)` **after** `:703`, mirroring `write_seeded_files` (`:619-635`) but chmod **`0o644`**, and asserting no path collides with a `seeded_files` entry |
| `generator/gen.py:178-202` `ownership_note` | "You own only `<entry_file>` … write your entire solution there" | brownfield variant: "`<entry_file>` contains this workspace's existing configuration — change it as needed." The `provider.tf`/`bin/app.ts`/`main.ts` don't-touch sentence is unchanged and still load-bearing (finding G1) |
| `generator/gen.py:239-262` `build_instruction_md` | body → language line → ownership note → trailer | insert `workspace_seed.premise` immediately after `shared_body`, **before** the language line, so it sits in the parity-checked shared prefix (`shared_prefix`, `:265-276`) |
| `generator/gen.py:1090-1575` `build_static_tiers_sh` | build → synth/plan → tier-0 → tier-1 → reward | add the optional idempotence step (§5); the reward expression at `:1535-1542` gains one more conjunct |
| `generator/gen.py:1824-1899` `generate_arm` | writes env/instruction/task.toml/tests/solution | no structural change. If §4's gate ships as a generated artifact, add a `tests/seed_asserts.sh` written the same way `static_tiers.sh` is (`:1844`) |
| `generator/check_reference_paths.py` | resolves `structural_asserts` against a hand-authored *correct* fixture | new `--seed` mode: resolve `seed_asserts` against the **generated, un-overlaid** task workspace (§4) |
| `arms/*/environment/Dockerfile` | named-file COPY | §3.1 |
| `mk/ci.mk:32` / `ci/run-ci.sh` | gen-sync, check-paths, falsifiability, grading-proof | add `seed-parity` per spec that declares `workspace_seed` |

### 3.3 What does *not* need to change (checked)

- **Read-only chmod discipline.** `write_seeded_files` (`:619-635`) chmods
  `0o444` and re-chmods `0o644` before overwrite so a regenerate is idempotent.
  The seed writer must **not** copy the `0o444` line; it must copy the
  "chmod writable before overwrite" idempotence trick.
- **`enforce_no_holdout_equipping`** (`generator/gen.py:2013-2078`) globs only
  skills/MCP/plugin material via `gates.equipping._discover_equipping_files`
  (`gates/equipping.py:55-70`). Seeded IaC is not in that set — no false
  positive, and correctly so (a seed is task content, not equipping).
- **No "workspace must be empty" assumption exists anywhere.** Searched
  `generator/tests/`, `gates/`, `ci/`. The two preflight patchers
  (`gen.py:535-563`, `:566-616`) deliberately *relaxed* their checks to
  "template has a `Resources` map" / "cdk.tf.json has a `resource` map" —
  a seeded, resource-bearing workspace satisfies them **more** easily than
  today's empty skeleton, not less. `patch_terraconstructs_preflight`'s
  `assert old_node_check in text` (`:610`) is about the *arm's* script text,
  not the workspace.
- **`gates/audit.py`** (Gate 2, toolchain-bypass) reads the trajectory only.
  Unaffected.

### 3.4 The equipping hash and seeded content

`gates/equipping.py:147-230` hashes: `instruction.md` (or `steps/*/instruction.md`,
`:73-103`), equipping files, the **resolved image digest**, and `extra_cfg`.
It does **not** walk `environment/`.

So the seed enters task identity **only through `image_digest`**
(`:200`, `_resolve_image_digest` `:106-144`). That is correct in principle —
the seed is baked into the image — but it has a documented soft spot: when
docker is unavailable/offline or the image isn't built locally, the function
falls back to the bare tag string and only `warnings.warn`s (`:136-143`). Two
different seeds under the same tag would then hash identically.

**Recommendation:** do **not** invent a second seed-hashing channel (a
competing definition of "what makes two trials incomparable" is exactly the
drift `gates/equipping.py`'s own docstring warns about). Instead, fold a
`workspace_seed_sha256` — sha256 over the canonical JSON of
`{arm: entry_file_body, extra_files: […]}` — into the **`extra_cfg`** dict the
runner already passes (`scripts/run-bench.sh`'s budget/equipping plumbing).
That reuses the existing manifest slot (`:218`), needs no
`HASH_SCHEME_VERSION` bump for existing specs (they pass no such key), and
survives the docker-unavailable fallback. Publish it in the result row so a
seed change is visible without re-deriving it.

---

## 4. Parity gate — proving the three seeds are equivalent

### 4.1 What "equivalent" must and must not mean

**Not** resource-count or resource-type parity. The whole thesis of the
benchmark is that one L2 construct decomposes into N Terraform resources
(`docs/scenario-candidates.md:58`, the `s3-bucket-hardening-decomposition`
row: "6+ HCL resources each silently omittable"). A census check would fail
every honest seed.

Equivalence is therefore defined **behaviourally, by declared facts**:

1. **Every arm's seed synth/plans green.** A seed that doesn't is not
   "existing infrastructure". This alone is a strong signal and is free.
2. **Every `seed_assert` holds on every arm it declares `applies_to`.**
   This is where the poison itself, and the infrastructure the change request
   will act on, are pinned.
3. **Coverage:** every `catch` in the spec whose mechanism lives in the seed
   must be named by at least one `seed_assert` — otherwise a seed could drift
   into being non-poisoned and nothing would notice. Enforce mechanically via
   a `seed_asserts[].pins_catch: <catch-name>` back-reference, checked the way
   `generator/check_tier1_coverage.py` already checks tier-1 asserts against
   policy files.

### 4.2 Where it lives

**Extend `generator/check_reference_paths.py`, do not write a new gate.**
It already does exactly this job for the *post*-agent artifact: it drops a
hand-authored fixture in place of `entry_file` in the **already-generated task
dir**, runs the arm's real toolchain (terraform / npm+node / cdktn), and
resolves declared paths through `generator/jsonpath_jq.py` + the generated
`tests/_assert_lib.sh::assert_check` — "the SAME code every trial actually
runs" (its docstring, ~lines 30-38).

The seed gate is the same procedure with the fixture overlay **omitted**:

```
make seed-parity SPEC=specs/<id>.yaml
  for arm in enabled_arms:
      task = tasks/anchor/<id>-<arm-dirname>          # as generated, untouched
      run the arm's toolchain in a sandbox copy of environment/<workspace>
      require: toolchain exits 0                       # "the seed is green"
      for a in seed_asserts where arm in a.applies_to:
          assert_check(a)                              # same jq, same op table
  report per-arm PASS/FAIL + a per-assert matrix
```

Exit-code convention should copy the existing one: `0` pass, `1` fail,
`3` NOT_AUTHORED (no `workspace_seed` in this spec) so `ci/run-ci.sh`'s
SKIP handling works unchanged.

Wire into `mk/ci.mk:32`'s per-spec loop alongside `check-paths`.

### 4.3 The residual, human half

A mechanical gate cannot prove "these three configurations describe the same
system"; it proves "these three configurations satisfy the same declared
facts". The declared facts are the spec author's claim. That is precisely the
status quo for `oracle.intent` (SCHEMA §4.1: "the text a human reviewer reads
to judge whether `structural_asserts` … actually encode what they claim to"),
and the honest move is to say so in the spec: `workspace_seed.premise` is the
human-readable equivalence claim, reviewed the way `oracle.intent` is.

---

## 5. Idempotence oracle

### 5.1 The blocking fact

`terraform plan -detailed-exitcode` returns **2 (changes present)** for any
plan against empty state. The generated static tier plans against an empty
working directory (`build_static_tiers_sh`'s toolchain block,
`generator/gen.py:1090-1195`; the hcl_raw chain at `:1160-1190`). So a
"second `plan -detailed-exitcode`" is meaningless offline unless there is
state. **The idempotence oracle is a live tier.**

(`apigw-redeploy` is the existing proof that the repo already reasons this
way: its `plan_command` carries `-refresh=false` specifically because a real
trial leaves `terraform.tfstate` behind —
`specs/apigw-redeploy.yaml:119-139`.)

### 5.2 Recommended shape

A new optional spec block, modelled on `verifier.live_check`:

```yaml
verifier:
  live_check: { enabled: true, hand_authored: true, gating: true,
                agent_role_name: "QALocalInvocationApplicationAdmin",
                concurrency_mode: "mutating" }
  idempotence:
    enabled: true
    gating: true          # default false — see reward semantics below
```

Per-arm command, injected **unconditionally by the generator** (the same
"cannot go missing because a spec author forgot a YAML key" discipline
`TERRACONSTRUCTS_BUILD_COMMAND` already uses, `generator/gen.py:124-134`):

| Arm | Idempotence step | Green |
|---|---|---|
| `hcl_raw` | `terraform plan -detailed-exitcode -refresh=false` (and a second run **with** refresh when the scenario's drift is provider-side normalisation) | exit `0` |
| `terraconstructs` | `npx cdktn synth` then, in `cdktf.out/stacks/<id>/`, `terraform plan -detailed-exitcode` | exit `0` |
| `awscdk` | `npx cdk diff --fail` against the deployed stack | exit `0` |

`cdk diff --fail` is the honest analogue: "the toolchain's own converged-state
check reports no pending change against what is actually deployed". A second
synth + template self-diff is **not** an analogue — CDK synth is
deterministic, so that check is vacuous by construction and would silently
hand the awscdk arm a free pass.

Note the expected asymmetry, and record it in the spec rather than
engineering it away: the `policy-json-string-normalization-diff` catch exists
because the *Terraform provider* round-trips a policy string through AWS and
compares the result. CloudFormation stores the template it was given, so the
awscdk arm is expected to be green here. That asymmetry **is the
measurement** (`docs/scenario-candidates.md:117-119`, C3 — 252 + 333 reactions).

### 5.3 Reward semantics

Two precedents exist in the tree:

- **Non-gating marker** — `tier1-not-verifiable` / `tf-plan-mock-sfn-unavailable`:
  written to `/logs/verifier/<name>`, `tee`'d, explicitly documented as never
  touching `reward.txt` (`generator/gen.py:1464-1496`).
- **Gating, fail-closed AND** — `verifier.live_check.gating`
  (`specs/SCHEMA.md:840-859`): final reward is `1.0` **iff** the static tiers
  say `1.0` **AND** the live check's `.outcome` is `"pass"`;
  `"fail_stale"` and `"not_verifiable"` both downgrade to `0.0`.

**Recommendation: gating, fail-closed, using the live_check precedent
verbatim** — and for the same reason SCHEMA §5 gives for `apigw-redeploy`:
for `policy-json-string-normalization-diff` the idempotence check is the
**only** signal that can ever catch the catch. Leaving it non-gating means
the catch the scenario exists to motivate can never cost a trial any reward.

Concretely:
- three outcomes, mirroring live_check's own contract: `converged` (exit 0),
  `pending_changes` (exit 2), `not_verifiable` (exit 1 / tool missing / no
  state found);
- `not_verifiable` downgrades to `0.0` when `gating: true` — never a silent
  pass;
- always write `/logs/verifier/idempotence-result.json` (the plan's
  `resource_changes` summary, so the *which resource keeps diffing* detail
  survives), whether gating or not. This mirrors
  `/logs/verifier/live_check-result.json`.
- `gating: true` requires `live_check.enabled: true` (model validator), for
  the same reason `LiveCheck` already rejects `gating` without `enabled`:
  no apply ⇒ no state ⇒ nothing to be idempotent about.

### 5.4 Falsifiability

`gates/oracle_falsifiability.py` needs one addition: a catch whose
`predicted_tier_caught` is the new `"idempotence"` tier (or reuse `"live"`)
must ship a `solution/broken/<catch>/solve.sh` that **mechanically
demonstrates** the pending diff, not merely asserts it — exactly the bar the
`"live"` branch already sets with `LIVE_ONLY_CONFIRMED_MARKER`
(`specs/SCHEMA.md:355-369`). For policy-JSON normalisation the offline
mechanical proof is available and cheap: seed a `terraform.tfstate` containing
the AWS-normalised policy string, then show `plan -refresh=false
-detailed-exitcode` returns `2` for the naive form and `0` for the
diff-suppression-friendly one. That is a *fixture-side* use of seeded state,
which does not touch the graded workspace and therefore does not raise the
parity problem §6 describes.

---

## 6. The pre-deployed-state sub-case (`lambda-alias-tracks-unpublished-latest`)

The seed is **code**; this scenario needs **state** — a deployed Lambda whose
alias already points at an unpublished `$LATEST`, so that the agent's change
appears to deploy but the alias keeps serving the old code.

Three options:

**(a) Seed `terraform.tfstate` into the workspace.** Cheapest, fully offline,
and it makes a static idempotence check possible (§5.4). **Rejected as the
graded mechanism:** there is no CloudFormation analogue of a state file, so
this is TF-arms-only. The awscdk arm would have to be dropped or given a
different, non-equivalent starting condition — at exactly the scenario where
the CDK/CFN engine behaviour is the thing being compared. Keep it for
*fixtures* (§5.4), never for the graded workspace.

**(b) Scenario-level fixture deploy.** `scenarios/anchor/` already has this
shape: `scenario.toml` (`[deploy] timeout_sec = 900`),
`scenario/cdk_app/`, and `deploy/deploy.sh` which runs
`cdk bootstrap` + `cdk deploy --all` under the `PRIMARY` profile at
`aws-bench env setup` time. `QARolesStack` rides this path today. Adding a
`PreDeployedLambdaStack` there would give every arm the same pre-existing
physical resources. **Costs:** (i) the fixture is **shared across every task
in the anchor scenario**, so it must survive the post-trial reset and must not
be mutated by unrelated tasks — a poisoned-*state* scenario mutates it by
construction; (ii) `CLAUDE.md`: "After changing anything under
`scenarios/anchor/**`, re-run `env setup` or resets fail with a
scenario-source-hash mismatch"; (iii) a second scenario (not `anchor`) would
be needed to isolate it, and `SCENARIO_ID = "anchor"` is a v1-wide constant
(`generator/gen.py:75`), so this is a real, non-trivial generator change.

**(c) Multi-step `pre_invoke`.** `DECISIONS.md` Amendment 26 §2
(`DECISIONS.md:5036-5052`) already pre-registers exactly this:
`steps/<name>/pre_invoke/pre_invoke.sh` runs **before that step's agent**,
inside the agent container, with credentials staged for
`[scenario].pre_invoke_role_name`, and is explicitly described as "where
`terraform apply` / `cdk deploy` of the previous step's IaC lives, and where
out-of-band … drift injection lives". Its `placeholder.json` feeds `{{…}}`
tokens into that step's prompt.

**Recommendation: (c), defer to multi-step.** Rationale:

- It is the only option where the pre-deployed state is *per-trial*, so a
  mutating scenario cannot poison a shared fixture for every other task.
- It is per-arm-correct by construction: the pre_invoke deploys **that arm's
  own seed**, so all three arms reach the same physical starting state through
  their own toolchain — which is a strictly better parity story than any
  hand-authored fixture stack.
- The machinery is already designed and partly built (`cdktn_bench/`,
  `CdktnMultiStepTrial`, Amendment 26), so this sub-case costs a spec, not a
  capability.
- Concretely: step 1's `pre_invoke` applies the seed (no agent turn spent, no
  tokens charged for setup); step 1 is the change request. A one-step task with
  a `pre_invoke` — i.e. `[[steps]]` of length 1 — is the minimal shape and
  avoids the `min_reward`/`mean` hazards entirely.

**Flag for the operator:** this makes `lambda-alias-tracks-unpublished-latest`
depend on multi-step landing. The other four target scenarios do not. Do not
let this one hold up the poisoned-workspace feature.

---

## 7. Prompt framing rules

`instruction.md` is assembled at `generator/gen.py:239-262` as
`shared_body → [premise] → language_line → ownership_note → [live note] →
TRAILER → [json fence]`, and everything before `language_line` is the
parity-checked shared prefix (`shared_prefix`, `:265-276`;
`self_check_parity`, `:1987-2006`; independently re-verified byte-for-byte by
`generator/check_parity.py`, whose docstring notes the full-file re-derivation
is the load-bearing check).

Rules for brownfield bodies, to be added to `specs/SCHEMA.md` §2.1:

1. **Two legal framings, declared not implied.** Add
   `instruction.framing: change_request | incident`.
   - *change request*: "Our naming convention changed — rename X to Y and roll
     it out." States a desired end state, exactly like the greenfield
     imperative.
   - *incident*: "Since this morning, requests to `/foo` return the previous
     version's response. Get the deployed service serving the current code."
     States an **observed symptom** and a desired end state. It must never
     state a diagnosis.
2. **Never "find the bug", "fix the mistake", "review this config".** Those
   turn a brownfield task into a code-review task and measure something else.
3. **No-solution-leak, seed side.** The seed carries **no comment that would
   not plausibly appear in real production config**. Specifically banned:
   any comment near the poisoned property; any `TODO`/`FIXME`/`NOTE`; and —
   new for seeds — the generator's own `Generated skeleton — generator/gen.py`
   /`Empty on purpose`/`TODO(agent)` headers (`gen.py:290-303`, `:370-381`,
   `:508-523`). Those headers currently tell the agent the file is bench
   scaffolding, which invites meta-reasoning about planted traps. Drop them for
   seeded entry files; regeneration-drift is already caught by the `gen-sync`
   CI check (clean working tree after `make gen`, `mk/ci.mk:9`), so the header
   is not load-bearing for that.
4. **No-solution-leak, prompt side.** The existing `instruction_concision`
   house rule (SCHEMA §2.1: "never paste a catch's threshold or valid-value
   set into the body") extends to: never name the pitfall's mechanism
   (`create_before_destroy`, "replacement", "perpetual diff", "publish a
   version"), never name the property that carries it, and never say the
   workspace contains a problem.
5. **The premise states facts, not warnings.** "This is deployed and healthy"
   is a fact. "Be careful, this SG is in use" is a warning and a hint. The
   in-use-ness must be discoverable from the *config*, which is where the
   `endpoint-consumes-the-sg` seed assert pins it.
6. **The ownership note must change.** Today it reads "You own only
   `<entry_file>` in this workspace — **write your entire solution there**"
   (`gen.py:180-186`). For brownfield: "`<entry_file>` holds this workspace's
   existing configuration; change it as needed." The don't-touch clause for
   `provider.tf`/`bin/app.ts`/`main.ts` stays verbatim — finding G1 is
   unaffected and still load-bearing.
7. **Parity is preserved for free**, because `premise` is spec-level and
   arm-agnostic, exactly like `seeded_files`' generated sentence
   (`gen.py:193-201`, and SCHEMA §2.5's own note that identical-across-arms
   text in the ownership note "does not threaten prompt parity").

---

## 8. Composition with multi-step

Checked against `docs/design/multistep-trial-investigation.md` §5
(lines 500-575) and Amendment 26.

**No conflicts.** The two features occupy disjoint parts of the task dir:

```
tasks/anchor/<id>-<arm>/
├── environment/          ← poisoned workspace lives HERE (image build context)
├── steps/<n>/instruction.md, tests/, pre_invoke/   ← multi-step lives HERE
└── tests/, solution/
```

The multistep memo's own generator rules make this explicit and *favourable*:

- rule 2 (`:561`): "**Never place step-2 material in `environment/`** — that
  *is* the image the agent lives in." The seed is step-**1** material by
  definition, so it belongs there. The memo's own proposed layout labels
  `environment/` as "docker build context **+ step-1 workspace seed**"
  (`:508`) — poisoned workspaces are already anticipated.
- The no-foreshadowing guarantee (`:542-548`) is unaffected: the seed is
  visible from turn one, which is exactly right — the agent is *supposed* to
  see the existing config.

Three interactions to get right:

1. **Equipping hash.** `compute_equipping_hash` already handles the
   steps shape (`gates/equipping.py:73-103`, `:220-228`: exactly one of
   `instruction_md_sha256` / `step_instructions` is present). Folding
   `workspace_seed_sha256` through `extra_cfg` (§3.4) works identically for
   both shapes — that is a second reason to prefer `extra_cfg` over a new
   top-level manifest key.
2. **Ordering inside `generate_arm`.** When both features are on,
   `write_environment` must run before any `steps/` emission, and the seed
   must be written **once**, into `environment/`, never per step. Add an
   assertion: `steps/*/workdir/` must not contain a path that also exists in
   the seeded workspace (a per-step overwrite of the seed would silently
   change the starting state and is almost certainly a spec bug).
3. **`pre_invoke` + seed = the §6 recipe.** A single-step task with a
   `pre_invoke` that applies the seed is the pre-deployed-state shape. It
   inherits Amendment 26 §3's open question verbatim: a `pre_invoke` deploy
   failure currently scores `0.0` rather than `invalid-infra`. With a seed
   that the harness applies, a flaky apply becomes an agent-visible failure —
   worth revisiting when the first such run exists.

---

## 9. Open questions for the operator

**Blockers (need a decision before implementation starts):**

- **B1. The `seeded_files` container gap (§3.1). — RESOLVED 2026-08-20, fixed
  now, NOT with a broad `COPY workspace/ ./`.** The read was confirmed:
  `apigw-openapi`'s `openapi/widgets-api.json` and `lambda/placeholder.zip`
  were absent at trial time and only the host-side gates saw them. Fix:
  `generator/gen.py::patch_dockerfile_workspace_copies` patches the generated
  task's Dockerfile (the mechanism that already patches `preflight.sh`),
  appending one **named** `COPY <workspace-subdir>/<path> ./<path>` per
  workspace file the arm's own COPYs don't already cover, under the WORKDIR
  derived from that arm's own workspace COPYs. The named-COPY discipline the
  arm Dockerfiles document is preserved. The invariant ("every git-tracked
  file in a workspace dir is in its Dockerfile's COPY set") is now a
  generator test — `generator/tests/test_dockerfile_workspace_coverage.py`,
  which fails on the pre-fix Dockerfile and would have caught this. Note this
  does **not** by itself answer Q4: the guard is a static Dockerfile/tree
  comparison, not a trial-time execution of `seed_asserts`.
- **B2. Does a poisoned workspace change the pre-registration?** The prereg's
  "empty-harness trial starts from a working, synth-able zero state"
  (SCHEMA §2.4) becomes "…from a working, synth-able **non-zero** state" for
  these scenarios. That reads as an amendment, not a clarification.
  Confirm — and confirm brownfield and greenfield tokens-to-green are
  **not** pooled (same refusal Amendment 26 §4 applies to N-step vs 1-step).

**Design calls the memo takes a position on but cannot settle alone:**

- **Q1.** Idempotence gating: fail-closed like `live_check.gating`
  (recommended, §5.3), or non-gating marker for a first scenario and promoted
  after one live run's evidence?
- **Q2.** `lambda-alias-tracks-unpublished-latest`: accept the multi-step
  dependency (recommended, §6), or authorise a second scenario dir
  (non-`anchor`) with its own fixture stack — which means unpicking
  `SCENARIO_ID = "anchor"` at `generator/gen.py:75`?
- **Q3.** Seed provenance headers: drop entirely from seeded entry files
  (recommended, §7 rule 3), or keep a minimal one and accept the
  meta-reasoning risk?
- **Q4.** Should `seed_asserts` be *executed at trial time* as a pre-agent
  tier (proving the container's starting state, not just the host's), or is
  the generation-time/CI gate (§4.2) sufficient? Executing them costs one
  extra synth/plan per trial; it would also have caught B1.
- **Q5.** Naming: `workspace_seed` vs. reusing/renaming `seeded_files`. The
  memo keeps them separate because their permissions and semantics are
  opposites (writable task content vs. `0o444` reference input), but two
  similarly-named fields is a real ergonomic cost.
- **Q6.** Does a poisoned workspace need its own falsifiability obligation —
  i.e. a `solution/broken/seed-unchanged/solve.sh` proving that submitting the
  seed **unmodified** scores `0.0`? Without it, a scenario whose change
  request is already satisfied by the seed would score `1.0` for doing
  nothing. Recommended: yes, make it mandatory for every spec with a
  `workspace_seed`; it is cheap (the fixture is the seed itself) and it closes
  the one failure mode unique to brownfield.

---

## Appendix — evidence index

| Claim | Where |
|---|---|
| Requirements for this feature | `docs/scenario-grades/2026-08-20-summary.md:39-50`, `:78-81` |
| Idempotence-oracle cluster (C3) | `docs/scenario-candidates.md:117-119`, `:196-197` |
| No CDK→TF synthesizer exists | `docs/scenario-candidates.md:169-176` |
| Empty-skeleton convention | `specs/SCHEMA.md` §2.4; `generator/gen.py:284`, `:344`, `:501` |
| Read-only seeded files | `specs/SCHEMA.md` §2.5; `generator/gen.py:619-635` |
| entry_file write points | `generator/gen.py:667-668`, `:681`, `:693-695` |
| Dockerfile COPY sets | `arms/hcl-raw/…:154-157`, `arms/awscdk/…:111-118`, `arms/terraconstructs/…:128-147` |
| Task Dockerfile is a byte copy | `generator/gen.py:660` + `diff` of arm vs task Dockerfile (empty) |
| Falsifiability runs host-side on `environment/<workspace>` | `gates/oracle_falsifiability.py:281-320` |
| Equipping-hash inputs | `gates/equipping.py:147-230`; image fallback `:106-144` |
| Prompt parity mechanism | `generator/gen.py:265-276`, `:1987-2006`; `generator/check_parity.py` |
| Reference-path gate (reuse target) | `generator/check_reference_paths.py` docstring + fixtures layout |
| static_tiers reward expression | `generator/gen.py:1535-1542` |
| live_check gating (AND, fail-closed) | `specs/SCHEMA.md:840-859`; `generator/gen.py:1604-1616` |
| Non-gating marker precedent | `generator/gen.py:1464-1496` |
| `-refresh=false` for post-apply working trees | `specs/apigw-redeploy.yaml:119-139` |
| Multi-step task-dir shape + generator rules | `docs/design/multistep-trial-investigation.md:500-575` |
| Harness deploys prior-step work via `pre_invoke` | `DECISIONS.md:5036-5052` (Amendment 26 §2) |
| Scenario-level fixture deploy | `scenarios/anchor/scenario.toml`, `scenarios/anchor/deploy/deploy.sh` |
| `SCENARIO_ID` is a v1-wide constant | `generator/gen.py:75-79` |
