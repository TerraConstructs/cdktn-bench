# Single-step seed deploy — making a brownfield premise true

**Status: DESIGN, not yet implemented.** Written 2026-08-25 against the tree at
that date.

> **IMPLEMENTED 2026-08-25**, in the same pass. The body below is the design as
> written and is left unedited — it is the contract the implementation was
> checked against. Two facts about the shipped result that the text above cannot
> know: §10's "Amendment 29" landed as **`DECISIONS.md` Amendment 31** (29 and 30
> were already taken), and §10 step 10's `solve.sh` stack-id fix was applied to
> **two** files, not one — `solution/broken/rename-replaces-an-in-use-security-group/solve.sh`
> carried the same wrong stack id. `docs/brownfield-seed-not-deployed.md` and
> `specs/SCHEMA.md` §2.7.1 are the live records. It resolves
> `docs/brownfield-seed-not-deployed.md` by **Option 1** (deploy the seed for
> real before the agent phase); Options 2 and 3 are rejected and are not
> revisited here.
>
> **AMENDED AGAIN by a third adversarial-review round** (`DECISIONS.md`
> Amendment 31 §11), which changed four things the notes below assert: the
> endpoint-attachment assert (and the group assert) are now **`eq`**, not
> `set_eq` — `set_eq` runs `unique`, so a legally-duplicable same-named
> leftover collapsed to one node and passed; `live_asserts` are narrowed by a
> **`jsonpath` shape rule** as well as an op rule, because a path that names a
> collection instead of iterating it passes `exists` on an empty account; the
> awscdk state proof distinguishes a **resolved** CloudFormation absence
> (`seed_absent`) from an unanswered question (`seed_unverifiable`); and the
> idempotence tier gained a **seed-movement guard**, because this mechanism
> turned that tier's "nothing was applied" probe into a tautology. §2.7.1 and
> `DECISIONS.md` §11 are authoritative over every note below.
>
> **AMENDED the same day by an adversarial review** (`DECISIONS.md`
> Amendment 31 §10). The shipped mechanism differs from the body below in six
> ways, all strengthening, and §2.7.1 — not this document — is authoritative
> where they disagree: (1) `live_asserts` may not use an op that passes on zero
> resolved nodes, so §5's "`min_length=1` makes the coupling structural" is only
> true once that rule is added; (2) the endpoint-attachment assert is `set_eq`,
> not `contains`, which on a string is jq's *substring* test and therefore
> passed against the post-solution account it was meant to exclude; (3) a
> **fourth** fail-closed layer runs in the verifier, because the three in §3
> all live inside a file `_prepare` executes only if it is on disk; (4)
> `-refresh=false` is asserted on the emitted bytes per arm, since the
> spec-field validator cannot see `terraconstructs`' hardcoded plan template;
> (5) `assert_check` distinguishes "could not resolve" (rc 2) from
> "contradicted" (rc 1); (6) `verifier.live_check.gating: false` is rejected
> alongside `enabled: false`.

This document is the contract for the implementation. It also records two
things nobody knew when the problem write-up was filed, both verified below and
both load-bearing:

* **terraconstructs' Terraform state does not live in `cdktf.out/`.** It lives
  at `/app/project/terraform.<stack-id>.tfstate`, an *absolute* path baked into
  the synthesized `cdk.tf.json` at synth time. `gen.py::IDEMPOTENCE_STATE_PROBE`
  has the wrong path for this arm, which is the whole of the
  `not_verifiable` result that cost the terraconstructs row its reward (§4.3).
* **A deployed seed breaks hcl-raw's tier-0 outright, today.** That arm's
  `plan_command` has no `-refresh=false`, so the moment a `terraform.tfstate`
  exists the offline verifier plan refreshes through dummy credentials and
  dies. Measured, not predicted (§4.4). Any seed-deploy design that does not
  fix this scores every hcl-raw brownfield trial 0.0 before the agent is judged.

---

## 1. The problem in brief

`specs/named-resource-replacement.yaml`'s `workspace_seed.premise` tells the
agent its workspace "is already deployed in this account". Nothing deploys it.
The trap is a *replacement* trap — renaming a literally-named security group
forces destroy-then-create, and the interface VPC endpoint holding that group
turns the destroy into a `DependencyViolation` — so every step of it needs the
group to exist **in AWS and in state**. With nothing deployed the trap cannot
fire on any arm, and `tests/live_check.py`'s discriminating assertion ("fail if
the OLD group survives") is satisfied *vacuously*: the oracle reports `pass`
while proving nothing.

The fix has two halves and they are not the same problem:

1. **Deploy the seed**, credentialed, before the agent phase, on a spec that
   declares no `steps:`.
2. **Put the resulting state where each arm's toolchain will find it**, so the
   agent's later `deploy`/`apply` is an *update* of existing infrastructure
   rather than a fresh create. This is the cross-arm asymmetry, and it is the
   hard half.

Plus a third that the original defect makes non-negotiable: **prove the seed
actually landed, before the agent starts, and abort loudly if it did not.**

---

## 2. What already exists (verified, not assumed)

### 2.1 A task-level `pre_invoke` is already a live single-step code path

`AwsBenchSingleStepTrial._prepare` runs it unconditionally for any task that
has the file on disk:

```python
# .venv/.../aws_bench/task/aws_trial.py:274-321
async def _prepare(self) -> None:
    if self.config.verify_env:
        await self._raise_if_contaminated()
    self._aws_placeholders = {tag: dict(v) for tag, v in self.config.exports.items()}
    await super()._prepare()                       # container up, healthcheck, agent setup
    if self.task.has_phase_script(ScriptType.PRE_INVOKE):
        output = await self._run_phase_script(
            script_type=ScriptType.PRE_INVOKE,
            role_type=RoleType.PRE_INVOKE,
            phase=self.task.config.pre_invoke,
            output_file_name=PLACEHOLDER_OUTPUT_FILE_NAME,   # "placeholder.json"
        )
```

`has_phase_script` resolves `<task_dir>/pre_invoke/pre_invoke.sh`
(`aws_bench/dataset/task_config.py:164-177` → `harbor/utils/scripts.py::discover_script`).
`ScriptRunner` uploads that whole directory to `/pre_invoke/` at *run* time —
not baked into the image — runs the entry script with `cwd=/pre_invoke`,
downloads `/logs/pre_invoke/` to `<trial_dir>/pre_invoke/`, and then
`rm -rf /pre_invoke /logs/pre_invoke` **for `PRE_INVOKE` specifically**
(`aws_bench/task/script_runner.py:249-300`, step 7).

`CdktnTrial.create` returns a plain `AwsBenchSingleStepTrial` for a stepless
task (`cdktn_bench/trial.py:298-316`), and `MultiStepTrial` does **not** override
`_prepare` (`harbor/trial/multi_step.py` defines `_run` and `_prepare_step`,
never `_prepare`), so `CdktnMultiStepTrial` reaches the same code through its
MRO. **The hook works for both forms with zero runner change.**

> **Therefore: this design requires NO change to `cdktn_bench/` or to any
> vendored library.** Everything below is generator + spec + docs.

### 2.2 `pre_invoke.deploy_prior` is not usable here, and does not need to be

`deploy_prior` is a field on `Step` only (`generator/spec_model.py:1195`); it
hard-errors on step index 0 (`spec_model.py:1670-1692`); and its runtime hook
`_run_step_pre_invoke` exists only on `CdktnMultiStepTrial`
(`cdktn_bench/trial.py:168-272`). A single-step spec has no surface to declare
it and no class to execute it.

What *is* reusable is its vocabulary. `deploy_prior` means "run this arm's
`output_contract.deploy_command` against `/app/project` under staged
credentials". The seed deploy means exactly the same thing, aimed at the same
directory, at an earlier moment. **So `output_contract.deploy_command` is reused
verbatim as the per-arm declaration, and gains a second legal consumer.** No
new per-arm command field is invented.

### 2.3 `seed_asserts` do NOT run in a trial — at all

The task asked this to be verified. It is worse than "post-agent only":
`seed_asserts` never enter a container in any phase.

* They are resolved only by `generator/check_reference_paths.py --seed`
  (`run_seed_mode`/`check_seed_arm`, lines 321-437), driven by
  `make seed-parity` (`mk/rails.mk:75-111`), which is wired into `make ci`
  per spec and deliberately **not** into `make check`.
* `grep -rn seed_asserts tasks/ generator/gen.py oracles/` returns **nothing**.
  No generated artifact carries them.
* They run against the *offline, un-overlaid, never-deployed* workspace. A
  green `make seed-parity` is evidence about three YAML bodies. It is **not**
  evidence that anything exists in an AWS account.

So `seed_asserts` cannot be "made" into the anti-vacuity gate — they are a
different instrument answering a different question (are the three seeds
equivalent?). The anti-vacuity gate is a **new, sibling** instrument answering
"is the seed live?", and §5 keeps them separate for that reason. Amendment 28's
deferred design-memo Q4 ("should `seed_asserts` also run at trial time?")
remains deferred and is **not** answered by this design.

---

## 3. The design

### 3.1 The hook

A brownfield spec that declares `workspace_seed.deploy` makes the generator emit,
per arm:

```
tasks/anchor/<id>-<arm>/
  pre_invoke/
    pre_invoke.sh        # generated; deploy + prove
    _assert_lib.sh       # generated; byte-identical copy of gen.py's ASSERT_LIB_SH
```

and, in `task.toml`:

```toml
[scenario]
scenario_id = "anchor"
agent_role_name = "QALocalInvocationApplicationAdmin"
pre_invoke_role_name = "QALocalInvocationApplicationAdmin"   # NEW

[pre_invoke]                                                  # NEW
timeout_sec = 2400.0
```

`pre_invoke/` is not a new directory concept: `gen.py:3977-3989` already owns
that path, currently as a `NotImplementedError` placeholder for
`pre_invoke_random` placeholders, with an `elif pre_invoke_dir.exists():
shutil.rmtree(...)` cleanup. That is the exact hook point.

### 3.2 Where it runs, in order

```
CdktnTrialQueue → gate.hold(MUTATING)          aws_bench/task/queue.py:32-117
  AwsBenchSingleStepTrial.run()                aws_trial.py:103-121
    Trial.run()                                harbor/trial/trial.py:154
      _prepare()                               aws_trial.py:274-321
        1  _raise_if_contaminated()
        2  seed {{placeholders}} from config.exports
        3  super()._prepare()                  harbor/trial/trial.py:185-192
             docker compose build   ← environment/workspace COPYed into the image,
             docker compose up --wait   so /app/project ALREADY HOLDS THE SEED
             healthcheck / skills / agent setup
    →   4  ***SEED DEPLOY***                   the pre_invoke hook, §3.1
      _run()                                   harbor/trial/single_step.py:30-43
             agent phase (staged AGENT creds)
             artifacts → verifier (tests/ uploaded fresh from host disk)
      _finalize()                              post_invoke, stop container
    if MUTATING: _reset_scenario_account()     ScenarioTrial(RESET), ~8.5-9 min
```

The seed deploy runs **inside the agent container**, in the same filesystem the
agent will open, after the workspace is materialized and before the agent's
first token. Anything it writes under `/app/project` is there when the agent
arrives. That is the entire mechanism by which cross-arm state gets "placed".

### 3.3 Credentials, role, region

`_run_phase_script` wraps the run in `_staged_credentials(RoleType.PRE_INVOKE)`
(`aws_trial.py:168-225`): `~/.aws/credentials` is written as the agent user, one
profile per account tag, `AWS_PROFILE`/`AWS_DEFAULT_PROFILE` pointed at the first
tag, every raw `AWS_*` credential env var emptied so host-forwarded credentials
cannot outrank the file, and the file `rm -f`'d on exit.

The role is `[scenario].pre_invoke_role_name`, falling back to
`OrganizationAccountAccessRole` when unset (`aws_creds.py:52-70`).

**The generator sets `pre_invoke_role_name` to the same value as
`agent_role_name`, and that is a rule, not a default.** Deploying the seed with
the broader org-access role could create resources the agent's own role cannot
subsequently modify or delete — turning a harness privilege asymmetry into a
fake agent failure, which is precisely the failure mode `DECISIONS.md`
Amendment 24 retired `QADeployApplicationRole` to avoid. *A seed the harness can
deploy must be a seed the agent can change.*

**Region must be exported by the script.** The staged credentials file carries
no region (`aws_bench/utils/credentials_provider.py:177-190` writes credential
keys only), no arm Dockerfile sets `AWS_DEFAULT_REGION`, and no `task.toml`
does. This already caused a live-invalidating bug — `gen.py:3288-3314` records
it: every `aws` call in `live_check.py` died with exit 253 `NoRegion` *before
reaching AWS*, reported as `not_verifiable`, gated to reward 0.0, with
`"failures": []` and a clean `exception_info`. The emitted `pre_invoke.sh`
carries the same two lines `tests/test.sh` now does:

```sh
: "${AWS_DEFAULT_REGION:=us-east-1}"
export AWS_DEFAULT_REGION
```

### 3.4 The emitted script

```sh
#!/usr/bin/env bash
# GENERATED by generator/gen.py::build_seed_pre_invoke_sh -- do not hand-edit.
# workspace_seed.deploy (specs/SCHEMA.md §2.7.1), spec <id>, arm <arm>.
#
# Run by aws_bench/task/aws_trial.py::AwsBenchSingleStepTrial._prepare inside the
# AGENT container, after the container is up and before the agent phase, with
# ~/.aws/credentials staged for [scenario].pre_invoke_role_name. ScriptRunner
# deletes /pre_invoke and /logs/pre_invoke afterwards, so the agent never sees
# this file, its output, or the fact that a harness deployed anything.
#
# NOT `set -e`: every failure must reach `fail`, which writes the machine-
# readable verdict BEFORE exiting non-zero.
set -uo pipefail

mkdir -p /logs/pre_invoke
PROOF=/logs/pre_invoke/seed-proof.json

fail() {   # fail <outcome> <reason> <exit-code>
  jq -n --arg o "$1" --arg r "$2" '{outcome:$o, reason:$r}' > "$PROOF" 2>/dev/null \
    || printf '{"outcome":"%s","reason":"%s"}\n' "$1" "$2" > "$PROOF"
  echo "SEED PROOF FAILED [$1]: $2" >&2
  exit "$3"
}

: "${AWS_DEFAULT_REGION:=us-east-1}"
export AWS_DEFAULT_REGION

. /pre_invoke/_assert_lib.sh
cd /app/project || fail seed_unverifiable "no /app/project in this container" 3

# ---- 1. DEPLOY: the arm's own output_contract.deploy_command, verbatim ------
echo "== seed deploy (<arm>) =="
if ! ( <deploy_command> ); then
  fail seed_absent "seed deploy command exited non-zero -- see stdout.log" 2
fi

# ---- 2. STATE PROOF: arm-specific, see §4 ----------------------------------
<SEED_STATE_PROOF[arm]>

# ---- 3. LIVE PROOF: workspace_seed.deploy.live_asserts, ARM-AGNOSTIC --------
failures=0
# one block per assert:
if ! aws 'ec2' 'describe-security-groups' \
        '--filters' 'Name=group-name,Values=internal-services-ssm-endpoint' \
        --output json > /tmp/seed-01.json 2>/tmp/seed-01.err; then
  fail seed_unverifiable "aws call for [old-group-is-live] failed: $(head -c 400 /tmp/seed-01.err)" 3
fi
assert_check 'old-group-is-live' '<compiled jq>' 'set_eq' '["internal-services-ssm-endpoint"]' \
  /tmp/seed-01.json || failures=$((failures + 1))
# ... more asserts ...

[ "$failures" -eq 0 ] || fail seed_absent \
  "$failures seed live assert(s) contradicted -- the account does not hold the seed this workspace describes" 2

# ---- 4. DECLARE ------------------------------------------------------------
jq -n '{outcome:"seed_deployed"}' > "$PROOF"
printf '{}\n' > /logs/pre_invoke/placeholder.json
```

Notes that are contract, not commentary:

* `_assert_lib.sh` is written from `gen.py`'s existing module-level
  `ASSERT_LIB_SH` constant (the same one `write_tests_dir` uses at
  `gen.py:3667`), so `assert_check`'s nine ops behave identically in the seed
  proof and in tier-0. **One owner, two destinations, byte-identical** — the
  same discipline `IDEMPOTENCE_COMMAND` uses.
* `placeholder.json` is written **last**, only on success. `ScriptRunner` checks
  the exit code (step 5) before it looks for the result file (step 6), so a
  failing run surfaces as `ScriptExecutionError`, not as the more confusing
  `ScriptResultFileNotFoundError`.
* `ScriptRunner` downloads `/logs/pre_invoke/` (step 4) **before** the exit-code
  check (step 5), so `seed-proof.json` and `stdout.log` reach
  `<trial_dir>/pre_invoke/` even on a failed seed. The operator always gets the
  reason.
* The container user: no arm Dockerfile sets `USER` and no `task.toml` sets
  `[agent] user`, so both the pre-invoke script and the agent run as root and
  the state files the seed writes are agent-writable. **If any arm ever adds a
  non-root `USER`, the seed deploy must run as that same user** — otherwise the
  agent's own `terraform apply` fails `EACCES` on a root-owned `terraform.tfstate`
  and a correct solution scores 0.0. A generator assertion covers this (§10).

---

## 4. Cross-arm state — the hard part

| arm | where deploy state actually lives | seed deploy command (spec-declared `deploy_command`) | how the agent's later run binds to it | state proof in `pre_invoke.sh` |
|---|---|---|---|---|
| `awscdk` | **In AWS.** CloudFormation stack `ScenarioStack`. No local state at all. | `npx cdk deploy --require-approval never ScenarioStack` | `bin/app.ts` passes construct id `"ScenarioStack"` with no `stackName` override, so the physical stack name is fixed; a later `cdk deploy` from the same workspace resolves the same name and issues an **UpdateStack**, through the account's one-time `CDKToolkit` bootstrap (`cdk-hnb659fds-*`, created by `scenarios/anchor/deploy/deploy.sh:17`). | `aws cloudformation describe-stacks --stack-name ScenarioStack --query 'Stacks[0].StackStatus'` must be `CREATE_COMPLETE` or `UPDATE_COMPLETE`. |
| `hcl_raw` | `/app/project/terraform.tfstate` — Terraform's implicit local backend. `arms/hcl-raw/environment/workspace/provider.tf:109-116`'s `terraform {}` block has **no** `backend` sub-block. | `TF_VAR_cdktn_bench_live=1 terraform init -input=false && TF_VAR_cdktn_bench_live=1 terraform apply -input=false -auto-approve` | Same container, same cwd, same file. The agent's `terraform` reads it. | `[ -s /app/project/terraform.tfstate ]` |
| `terraconstructs` | `/app/project/terraform.<workspace_id>.tfstate` — **NOT** `cdktf.out/stacks/<id>/terraform.tfstate`. See §4.3. | `CDKTN_BENCH_LIVE=1 npx cdktn deploy --auto-approve <workspace_id>` | The path is an **absolute** string written into `cdk.tf.json`'s `backend.local.path` at synth time from `process.cwd()`. Every later synth run from `/app/project` regenerates the identical absolute path, in offline *and* live mode. | `[ -s /app/project/terraform.<workspace_id>.tfstate ]` |

### 4.1 awscdk — no state to place, one name to preserve

Nothing local needs seeding. The only invariant is the physical stack name, and
`bin/app.ts` is non-agent-editable and generator-owned, so the agent cannot move
it. The seed deploy must NOT pass `-o` or `--app`: it must use the workspace's
own `cdk.json` (`"app": "npx tsc -p tsconfig.json && node bin/app.js"`, which
self-builds), so the seed and the agent deploy the same app definition.

One consequence worth stating: because CloudFormation's replacement order is
create-new-then-delete-old, this arm is *expected* to converge on the naive
rename. That asymmetry is the measurement (spec header, lines 26-29); a
deployed seed is what finally lets it be observed rather than asserted.

### 4.2 hcl-raw — trivial to place, and the offline/live switch is mandatory

`provider.tf` hardcodes dummy `access_key`/`secret_key` unless
`TF_VAR_cdktn_bench_live=1`, and the AWS provider ranks an explicit
`access_key` **above** every ambient credential source. Without that variable
the seed apply fails with `InvalidClientTokenId` — loudly, which is the correct
failure, but it must not be discovered live. It is part of the spec-declared
`deploy_command`, exactly as `solution/solve.sh:120-124` already spells it.

### 4.3 terraconstructs — where the state actually is (resolved)

`docs/brownfield-seed-not-deployed.md` and the state-asymmetry recon both leave
this open: a real `cdktn deploy --auto-approve` reported *"Apply complete!
Resources: 6 added"* and the SG + endpoint were confirmed in AWS, yet no
`terraform.tfstate` existed at `cdktf.out/stacks/<id>/`. **It is resolved, and
the answer is that the path was never right.**

Evidence, three independent sources agreeing:

1. `cdktn`'s own source — the default local backend path:
   ```js
   // packages/cdktn/src/backends/local-backend.ts:23
   props.path || path.join(process.cwd(), `terraform.${stackId}.tfstate`)
   ```
   and `TerraformStack` installs it whenever the stack declares no backend:
   ```js
   // packages/cdktn/src/terraform-stack.ts:340-341
   const backends = this.findAll(TerraformBackend.isBackend);
   return backends[0] || new LocalBackend(this, {});
   ```
2. A real synthesized `cdk.tf.json` from this repo's own jobs directory
   (`jobs/claude-sonnet-5/2026-08-20__17-16-22/apigw-redeploy-terraconstructs__W2J5uiF/agent/claude-code.txt:45`):
   ```json
   {"backend": {"local": {"path": "/app/project/terraform.hello-version-api.tfstate"}}}
   ```
   `hello-version-api` is that scenario's `workspace_id`.
3. The agent in the same trial `cat`-ing the file at
   `/app/project/terraform.hello-version-api.tfstate` and getting a version-4
   state document back.

So for `named-resource-replacement` the state path is
`/app/project/terraform.internal-services-network.tfstate`, and
`gen.py:3018`'s `IDEMPOTENCE_STATE_PROBE["terraconstructs"] =
"cdktf.out/stacks/__WORKSPACE_ID__/terraform.tfstate"` is simply wrong. The
`not_verifiable` verdict in both live runs was the probe failing, not the
deploy.

Three follow-on consequences:

* **The probe constant is fixed** to `terraform.__WORKSPACE_ID__.tfstate`
  (still workspace-root-relative, as its own docstring says). This design
  depends on that path, so per the brief it is resolved here, not deferred.
* **`gen.py`'s post-synth "state vanished" re-probe (rc `9`) stops being a live
  hazard**, because the state file is not inside the directory `cdktn synth`
  rewrites. Keep the re-probe — it is cheap and the guarantee is the contract,
  not the mechanism — but point it at the absolute
  `/app/project/terraform.<id>.tfstate` and expect it never to fire. `SCHEMA.md`
  §5.1's "Not yet exercised live" paragraph is amended accordingly.
* **The backend path is identical in offline and live mode.** `CDKTN_BENCH_LIVE`
  only strips the dummy credentials and the mock-STS endpoint override from
  `providerConfig` (`environment/app/main.ts:52-62`); `ensureBackendExists`
  runs either way. That is what makes the handoff work: the harness synths live,
  the agent synths however it likes, and both resolve the same state file.

### 4.4 A deployed seed breaks hcl-raw's tier-0 today — measured

This is not in the problem write-up and it blocks the whole design.

`specs/named-resource-replacement.yaml:401-404` declares:

```yaml
plan_command: >-
  terraform init && terraform validate &&
  terraform plan -input=false -out=plan.tfplan &&
  terraform show -json plan.tfplan > plan.json
```

No `-refresh=false`. With a state file present, `terraform plan` refreshes; the
verifier runs offline, so `provider.tf` is in dummy-credential mode; the refresh
signs a real EC2 call with a fake key and the plan dies. Observed verbatim in
`jobs/rerun-named-resource-replacement/2026-08-25__01-43-17/named-resource-replacement-hcl-r__rtmpCyN/verifier/test-stdout.txt:42-46`:

```
aws_vpc.internal_services: Refreshing state... [id=vpc-05c33a26cbf19bef8]

Planning failed. Terraform encountered an error while generating this plan.

PLAN FAILED
```

That row's 0.0 was read as "the agent's config is bad". It was the verifier
failing on state the agent's *own* successful apply created. Once the harness
seeds state deliberately, this fires on **every** hcl-raw brownfield trial,
including a perfect one.

The terraconstructs arm is already immune: `gen.py` injects `-refresh=false`
into that arm's generated plan step (`tasks/anchor/…-terraconstructs/tests/static_tiers.sh:59`).
awscdk is immune by construction (`cdk synth`, no state).

**Fix:** every brownfield arm's `plan_command` must carry `-refresh=false`, and
the generator enforces it — `Spec._brownfield_plan_must_not_refresh` hard-errors
at spec load, citing this measurement, for any spec with `workspace_seed` whose
enabled arm declares a `terraform plan` without the flag. The same flag on a
state-bearing plan is what `SCHEMA.md` §5.1 already reasons about for the
idempotence tier ("a refreshing plan re-contacts AWS through the arm's *offline*
dummy-credential provider config and 403s").

Grading is unaffected: every `tf_jsonpath` in this spec reads
`$.planned_values.…` or `$.configuration.…`, and `planned_values` is the full
desired end state of every resource, including unchanged ones — not a changeset.

---

## 5. Anti-vacuity: the seed's existence is a fail-closed pre-condition

The defect that started this was an oracle that passed for free. The mechanism
below makes "the seed was not deployed" impossible to reach the agent phase.

### 5.1 Three layers, all fail-closed

**Layer 1 — the deploy must exit 0.** A non-zero exit raises
`ScriptExecutionError` out of `ScriptRunner.run` (`script_runner.py:284-289`) →
out of `_prepare` → caught by `Trial.run`'s generic handler
(`harbor/trial/trial.py:166-170`), which calls `_record_exception` and **never
calls `_run()`**. No agent phase, no verifier, no `verifier_result`, no reward
key at all.

**Layer 2 — the state artifact must exist.** The arm-specific probe of §4. This
catches the subtle case the terraconstructs run exhibited: a toolchain that
reports success while leaving nothing the next phase can use.

**Layer 3 — `workspace_seed.deploy.live_asserts`.** Declarative, arm-agnostic
assertions resolved against real AWS CLI responses, through
`generator/jsonpath_jq.py` and `_assert_lib.sh::assert_check` — the same
compiler and the same nine ops tier-0 uses. Arm-agnostic on purpose: the account
is arm-agnostic, which is the same principle that makes
`tests/live_check.py` byte-identical across all three arms.

For `named-resource-replacement`, the assert that closes the specific hole is
the exact negation of the live oracle's discriminating assertion:

* live oracle, post-agent: *"NO security group named `internal-services-ssm-endpoint` remains."*
* seed live assert, pre-agent: *"a security group named `internal-services-ssm-endpoint` EXISTS."*

If the second is false the first is vacuous, and the trial never starts.

### 5.2 Coverage rule

At least one `live_asserts` entry **must** set `pins_catch`, naming the catch
whose live oracle depends on that pre-condition. Same shape and same reason as
`seed_asserts[].pins_catch` (`spec_model.py:1478-1499`): without a
back-reference the live asserts can drift into proving "something got deployed"
rather than "the poisoned thing is deployed" — which is the vacuity one level up.

And `deploy` may not be declared without `live_asserts` (`min_length=1`), so a
seed deploy without an existence proof is not expressible.

### 5.3 Three verdicts, and why abort beats reward 0.0

`seed-proof.json` carries an `outcome`, deliberately shaped like `live_check`'s
and `idempotence`'s own three-valued contracts (`SCHEMA.md` §5, §5.1):

| outcome | exit | meaning | effect |
|---|---|---|---|
| `seed_deployed` | 0 | deploy exited 0, state artifact present, every live assert held | trial proceeds |
| `seed_absent` | 2 | the deploy failed, or the state artifact is missing, or a live assert **resolved and was contradicted** | trial aborts in `_prepare` |
| `seed_unverifiable` | 3 | the proof could not be run — no `aws`, no credentials, an API error, a jq error, no `/app/project` | trial aborts in `_prepare` |

Both non-`seed_deployed` verdicts abort. This is the same fail-closed rule as
"anything not `pass` downgrades reward to 0.0", **pushed one phase earlier and
made stronger** — and the strengthening is the point:

> A reward of 0.0 is a *measurement*. It says the agent failed. A seed that was
> never deployed did not produce an agent failure; it produced **no measurement
> at all**. Recording it as 0.0 would repeat the original defect with the sign
> flipped — a number that looks like evidence and is not.

Aborting in `_prepare` yields a `result.json` with `exception_info` set and no
`verifier_result`, which `metrics/extract_signals.py:139-142` already renders as
`INFRA-FAIL: <exception_type>` and drops from every rollup. The honest outcome
falls out of existing code.

`_finalize()` still runs (it is in the `finally` block), so the container is
still stopped and — because `super().run()` returns normally after recording the
exception rather than re-raising — `_reset_scenario_account()` still runs. **A
half-deployed seed is still torn down.**

### 5.4 What this does not replace

`seed_asserts` (generation-time, offline, "the three seeds declare the same
system") and `live_asserts` (trial-time, pre-agent, "the account holds it") are
separate instruments and both stay mandatory. `make seed-parity` remains the
gate that a seed is green and equivalent; it is not, and never was, evidence
about an account.

---

## 6. Schema surface

New sub-block `workspace_seed.deploy`, documented as `SCHEMA.md` **§2.7.1**.
The full YAML an author writes is in the companion `spec_surface` block; the
rules are:

* **`deploy` is optional.** Omitted, a `workspace_seed` spec generates exactly
  as today — the regression guarantee §2.7 already claims extends to this field.
* **`deploy` requires `verifier.live_check.enabled: true` and
  `concurrency_mode: "mutating"`.** A seed deployed into an account with no
  post-trial reset contaminates it; a seed deployed with no live oracle is
  spend with no measurement. Both are hard errors at spec load.
* **`deploy` requires `output_contract.deploy_command` on every ENABLED arm.**
  Same message shape as `spec_model.py:1670-1692`'s existing multi-step check.
  `_deploy_command_only_with_steps` is renamed `_deploy_command_has_a_consumer`
  and now accepts either consumer: a `steps[].pre_invoke.deploy_prior`, or a
  `workspace_seed.deploy`. A `deploy_command` with neither is still rejected.
* **`live_asserts` is required, `min_length=1`, and ≥1 entry must set
  `pins_catch`.**
* **`timeout_sec`** (default `1800.0`) becomes `task.toml`'s task-level
  `[pre_invoke] timeout_sec`. aws-bench's own default is `600.0`
  (`task_config.py:69-77`) — far too short for a real apply plus an interface
  VPC endpoint reaching `available`. **This value is not scaled by
  `--timeout-multiplier`**: `_run_phase_script` passes `phase.timeout_sec`
  straight to `ScriptRunner`, unlike agent/verifier timeouts which go through
  `Trial._resolve_timeout_sec`. Size it for the slowest runner you will use.
* **`role_name`** (optional) overrides `[scenario].pre_invoke_role_name`; the
  default is `verifier.live_check.agent_role_name` (§3.3).

`live_asserts[].aws` is a **list of argv tokens**, not a shell string: the
generator emits each token single-quoted, so no quoting or word-splitting
question exists. Validator rejects empty tokens, embedded newlines or single
quotes, a first token starting with `-`, and the tokens `--profile`,
`--region`, `--endpoint-url`, `--output` (the harness owns those).

---

## 7. Teardown, reset, concurrency

Nothing new is needed, and nothing new should be added.

* `concurrency_mode: "mutating"` already makes `AwsBenchSingleStepTrial.run()`
  call `_reset_scenario_account()` after every settled trial
  (`aws_trial.py:112-116`), which runs `ScenarioTrial(RESET)`: `reset.sh`, an
  infra diff/restore, and two account-wide CloudFormation-resource-type
  fastscans. Those fastscans are what sweep raw, non-CFN resources — i.e.
  exactly the VPC/subnet/SG/endpoint the TF arms' seed creates — and stack
  deletion removes the awscdk arm's `ScenarioStack`. This is the same mechanism
  that already cleans up the *agent's* deploys today; the seed's resources are
  indistinguishable from them.
* The reset runs **only after** a trial, never before
  (`aws_trial.py:103-116`, no pre-run call anywhere). So the seed deploy always
  starts from the previous trial's restored baseline.
* `_ScenarioAdmissionGate` (`aws_bench/task/queue.py:32-117`) holds the
  scenario's exclusive writer lock across `trial.run()` — which includes both
  the seed deploy and the reset — so no other trial on `anchor` can observe or
  race the seed. Two brownfield trials never share an account.
* A failed seed deploy still resets (§5.3). A *cancelled* trial does not —
  `super().run()` re-raises cancellation before the reset line — which is
  pre-existing behaviour and pre-existing operator guidance (`aws-bench env
  cleanup`), not something this design changes.
* **No `post_invoke` teardown script is added.** A second cleanup path that can
  disagree with the reset is a liability; the reset is authoritative.

---

## 8. Cost

**Per trial, unavoidably.** The seed cannot be deployed once and reused, for
three independent reasons, any one of which is sufficient:

1. The post-trial reset is unconditional for a mutating task and has no
   keep-this carve-out. It destroys exactly what the seed created.
2. Both TF arms need the state **file** inside the agent's container
   filesystem, and containers are per-trial. Even a surviving account-side
   deployment would have to be re-materialized locally.
3. A persistent seed would put the account permanently out of baseline, which
   is the condition `_raise_if_contaminated` refuses to start a trial on.

**Wall clock:** roughly **+3-6 minutes per trial**, dominated by the interface
VPC endpoint reaching `available` (~2-3 min) plus provider init and apply. The
`[pre_invoke] timeout_sec` default of `1800.0` is generous headroom, not an
estimate. For context, each brownfield trial already carries a mandatory
~8.5-9 minute post-trial reset (`DECISIONS.md:3956-3964`,
`docs/teardown-experiment-results.md:295-320`), so the seed adds roughly
40-70% on top of the fixed overhead — noticeable, not dominant.

**Dollars:** negligible. A VPC, a subnet, a security group and one interface
endpoint. The endpoint is the only metered item at roughly $0.01/AZ/hour; over
a trial's lifetime that is under a cent. Deploy-time API calls are free. The
real cost is the wall clock, which is a scheduling constraint on batch size —
six mutating trials remain strictly serial per scenario.

---

## 9. Measurement integrity

Seed-deploy time and tokens must never be attributed to the agent. Three
structural guarantees, no discipline required:

1. **Zero tokens by construction.** `pre_invoke.sh` is a shell script. No LLM
   runs. `metrics/extract_signals.py::sessions_for` globs
   `**/sessions/projects/*/*.jsonl` under the trial dir; the pre-invoke phase
   writes only `<trial_dir>/pre_invoke/{stdout.log,seed-proof.json,placeholder.json}`,
   which matches no such path and contributes no row.
2. **Zero cost by construction.** `extract_signals` reads `cost` from
   `result.json`'s `agent_result.cost_usd` (or the step's), which Harbor
   populates from the agent run only.
3. **Nothing leaks into the agent's context.** `ScriptRunner` step 7
   `rm -rf /pre_invoke /logs/pre_invoke` for `PRE_INVOKE` specifically, before
   the agent phase begins. The agent cannot read the script, the deploy log, or
   the proof. What it *does* see — `terraform.tfstate`, `.terraform/`,
   `cdk.out/`, a state-bearing workspace — is the brownfield premise being
   true, which is the entire point.

**One standing obligation.** `_prepare` is inside the trial's
`started_at`→`finished_at` window, so any *trial-duration* metric would include
the seed deploy. No metric reads a duration today (`wall_seconds` appears only
in `metrics/test_validate_result.py`'s fixture). If one is ever added it must
read the agent phase's own window, never the trial's. Recorded here and in the
amendment so it is a decision rather than an oversight.

**And the standing metric rule is unchanged and still manual:** brownfield
tokens-to-green is a separate stratum (Amendment 28 §6).
`metrics/tokens_to_green.py::cell_key` is `(arm, model, harness)` with no
scenario-form dimension, so `make metrics` must not be run over a results
directory containing both forms. Deploying the seed does not change that; it
makes the brownfield rows worth stratifying for the first time.

---

## 10. Implementation plan

Ordered; each step is independently checkable offline.

1. `generator/spec_model.py` — add `SeedLiveAssert` and `WorkspaceSeedDeploy`
   models; add `deploy: WorkspaceSeedDeploy | None = None` to `WorkspaceSeed`.
2. `generator/spec_model.py` — rename `_deploy_command_only_with_steps` to
   `_deploy_command_has_a_consumer`; accept `workspace_seed.deploy` as a second
   legal consumer.
3. `generator/spec_model.py` — `_seed_deploy_requires_deploy_command`,
   `_seed_deploy_requires_live_and_mutating`,
   `_brownfield_plan_must_not_refresh`.
4. `generator/gen.py` — fix `IDEMPOTENCE_STATE_PROBE["terraconstructs"]` to
   `terraform.__WORKSPACE_ID__.tfstate`; repoint the in-command post-synth
   re-probe at the absolute path.
5. `generator/gen.py` — add `SEED_STATE_PROOF: dict[Arm, str]`.
6. `generator/gen.py` — add `build_seed_pre_invoke_sh(spec, arm)`.
7. `generator/gen.py` — write/remove `pre_invoke/pre_invoke.sh` and
   `pre_invoke/_assert_lib.sh` at the existing `pre_invoke_dir` site
   (`gen.py:3977-3989`); assert the arm has no non-root `USER`.
8. `generator/gen.py::build_task_toml` — emit `[scenario] pre_invoke_role_name`
   and a task-level `[pre_invoke] timeout_sec`, both guarded on
   `spec.workspace_seed and spec.workspace_seed.deploy`.
9. `specs/named-resource-replacement.yaml` — add `deploy`, add
   `deploy_command` per arm, add `-refresh=false` to the hcl_raw
   `plan_command`.
10. `tasks/anchor/named-resource-replacement-terraconstructs/solution/solve.sh`
    — hand-authored fix: `npx cdktn deploy --auto-approve named-resource-replacement`
    names the **spec id**, but the stack id is `internal-services-network`
    (`workspace_id`). That command cannot have worked.
11. `specs/SCHEMA.md` — new §2.7.1; amend §2.6's `deploy_command` paragraph;
    amend §5.1's terraconstructs state path and its "not yet exercised live"
    note.
12. `DECISIONS.md` — Amendment 29 (DRAFT), and an Amendment 28 §4 correction
    recording the state-path finding.
13. `generator/tests/test_seed_deploy.py` — new suite (§11).
14. `docs/brownfield-seed-not-deployed.md` — status → RESOLVED BY DESIGN,
    pointing here; keep the voided rows table.
15. `make gen-all`, `make check`, `make falsifiability` — offline proof.

---

## 11. Test plan (all offline)

* **Byte-identity.** `make gen-all` with `deploy` absent from every spec must
  leave every task dir unchanged except the three
  `named-resource-replacement-*` trees, whose only diff is the fixed
  terraconstructs state path in `tests/test.sh`. Every greenfield task
  byte-identical.
* **Emission.** With `deploy` declared: `pre_invoke/pre_invoke.sh` +
  `pre_invoke/_assert_lib.sh` exist and are executable on all three arms;
  `_assert_lib.sh` is byte-identical to `tests/_assert_lib.sh`; `task.toml`
  carries `pre_invoke_role_name` equal to `agent_role_name` and a
  `[pre_invoke] timeout_sec`; `pre_invoke.sh` contains the arm's
  `deploy_command` verbatim, the region export, the arm's state proof, and one
  `assert_check` per live assert.
* **Removal.** Dropping `deploy` from the spec and regenerating removes
  `pre_invoke/` entirely and reverts `task.toml`.
* **Validators, each with a one-line spec mutation.** `deploy` without
  `deploy_command` on one arm; `deploy` with `live_check.enabled: false`;
  `deploy` with `concurrency_mode: "read-only"`; `live_asserts: []`;
  `live_asserts` with no `pins_catch`; an hcl_raw `plan_command` missing
  `-refresh=false`; an `aws` token starting with `-`; an `aws` token containing
  `--region`.
* **`deploy_command` consumer check.** A stepless spec with `deploy_command`
  and no `workspace_seed.deploy` still raises. A spec with both consumers is
  legal. The existing multi-step `deploy_prior` path is unchanged
  (`generator/tests/test_multistep_emission.py:464-531` still passes untouched).
* **jq compilation.** For each `live_asserts` entry, `jsonpath_to_jq` produces
  the expected filter, and running `assert_check` against a checked-in fixture
  of a real `aws ec2 describe-security-groups --output json` response passes
  for the seeded shape and fails for an empty `{"SecurityGroups": []}` — the
  vacuity case, proven mechanically.
* **Falsifiability, unchanged.** `make falsifiability` runs offline against
  `tests/static_tiers.sh` and never reaches `pre_invoke/` or `tests/test.sh`;
  `solution/broken/seed-unchanged/` must still score `< 1.0` with a graded
  artifact.
* **`make seed-parity SPEC=specs/named-resource-replacement.yaml`** still
  passes: `deploy` changes nothing about the offline seed.
* **`make check` / `make test-gates`** green.

---

## 12. Open risks

1. **`_assert_lib.sh` self-containment is assumed, not proven.** It is written
   as a companion to `static_tiers.sh`. If `assert_check` depends on anything
   that script sets, sourcing it from `pre_invoke.sh` breaks. Verify by
   sourcing it in a bare shell during implementation; if it is not
   self-contained, split the shared half rather than forking it.
2. **`cdktn deploy`'s exit code on partial apply is unverified.** If it can
   exit 0 having applied only some resources, Layer 1 misses it — which is
   exactly why Layers 2 and 3 exist. Watch the first live run.
3. **The interface VPC endpoint may not be `available` when `apply` returns.**
   If the live asserts read the endpoint's state they may need the same
   poll-with-timeout shape `live_check.py` uses (`POLL_TIMEOUT_S = 120`). Start
   by asserting only the security group's existence, which is immediate, and
   add endpoint asserts only if a poll helper proves necessary.
4. **`cdk deploy` at pre-invoke time may write `cdk.context.json` into the
   workspace**, a file the agent will see. Harmless in content but it is a byte
   the brownfield-prompt-surface sweep
   (`generator/tests/test_workspace_seed.py::TestBrownfieldPromptSurface`) does
   not currently cover, because it did not exist at generation time. Confirm it
   carries no scenario vocabulary, or delete it at the end of `pre_invoke.sh`.
5. **The terraconstructs state path resolution is from `cdktn` source and from
   a *different scenario's* live `cdk.tf.json`.** Both are strong; neither is a
   `named-resource-replacement` post-deploy directory listing. The first live
   run must capture `find /app/project -iname '*.tfstate*'` immediately after
   the seed deploy. Layer 2 does exactly that and fails closed if it is wrong —
   which is the design working, not the design failing.
6. **A regenerated `tests/test.sh` moves this scenario's task bytes**, so its
   `equipping_hash` moves. Correct — the three published rows are already void
   (`docs/brownfield-seed-not-deployed.md`) — but the amendment must say so, and
   no pre-fix row may be pooled with a post-fix one.
7. **Amendment 28 stays DRAFT** until a live brownfield run under this
   mechanism. This design does not promote it; it makes the promotion criterion
   reachable for the first time. Amendment 29 (this mechanism) enters DRAFT
   alongside it and is promoted by the same run.
8. **Batch B unblocks, and inherits every rule here.** Four more brownfield
   scenarios assume a deployed seed. Each needs its own `deploy` block, its own
   `live_asserts` with a `pins_catch`, and its own `-refresh=false`. The
   generator enforces all three; none of them is a review-time convention.
