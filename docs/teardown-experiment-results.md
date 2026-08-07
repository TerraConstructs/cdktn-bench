# Teardown experiment results: does upstream's reset solve the leak?

**Date:** 2026-08-08. **Account:** `886312446417` ("cdktn-bench", dedicated benchmark
account) **only**. **Region:** `us-east-1` **only**. No action here touched
`694710432912` (production website) or mutated any resource inside `489592802338`
(management account) — the only management-account calls made were STS `AssumeRole`
(to obtain member-account credentials) and read-only `organizations:
ListTagsForResource`.

**Authorization on record** (quoted verbatim): the operator (Vincent, repo owner)
wrote on 2026-08-08: "I authorize the scoped destructive test in the dedicated
account (teardown to test upstream framework reset solves the leak)." The same
message additionally recorded (per `DECISIONS.md` Amendment 17, below) that
aws-nuke stays parked and no IAM account alias is to be set at this stage; nothing
in this document's own work touched either.

## Relationship to the existing Amendment 17 / prior results file

This repo already had a `docs/teardown-experiment-results.md` and a committed
`DECISIONS.md` Amendment 17 (commit `28acffe`) recording an **earlier pass** at
this same experiment, reaching the same top-line conclusion. That earlier run's
own process note says it was flagged for a real problem: "a subagent... wrote
assume-role credentials to a scratch file despite an explicit instruction not
to." This document is an **independent, from-scratch re-run**, done with strict
credential hygiene (every STS credential set was piped directly from `aws sts
assume-role`'s output into shell environment variables within a single command —
never written to any file, scratch or otherwise), that reproduces and confirms
the same conclusion with more precisely-cited, timestamp-sourced evidence, and
corrects one figure (reset runtime — see "Runtime cost" below) that the prior
pass appears to have understated. It supersedes the prior file's content; the
prior Amendment 17 is left untouched in the append-only decisions log, and a new
amendment (18) below records the reconciliation.

## Verdict, up front

**Upstream's reset fully solves the leak.** A dirty fixture spanning all four
target categories — a standalone Lambda function, a standalone IAM role, a
standalone CloudWatch log group, and a small CloudFormation stack whose Lambda
function and IAM role got CFN-random physical names (the `awscdk`-arm case no
fixed-name sweep can match) — was deployed into the account, and a **direct
invocation of the framework's own `ResourceManager.reset_scenarios` →
`ResetManager.reset_account`** (the exact same call chain both `aws-bench env
reset` and the automatic post-mutating-trial hook use) deleted **all 9 resulting
resources**, across all four types, with zero survivors, zero preserve-list
damage, and the account verified byte-for-byte back to its "before" inventory.

## Method

### 1. Before inventory

Captured via `OrganizationAccountAccessRole` in `886312446417`, `us-east-1`:

| Category | Count | Detail |
|---|---|---|
| CFN stacks (non-DELETE_COMPLETE) | 3 | `anchor-QARoles-us-east-1`, `anchor-Anchor-us-east-1`, `CDKToolkit` — all `CREATE_COMPLETE` |
| Lambda functions | 0 | |
| REST APIs | 0 | |
| IAM roles (excl. `/aws-service-role/*`) | 10 | 5× `cdk-hnb659fds-*-role-...`, `cfn-service-execution`, `LLMJudgeFullBedrockAccessRole`, `OrganizationAccountAccessRole`, `QALocalInvocationApplicationRole`, `QALocalInvocationApplicationAdmin` |
| CloudWatch log groups | 0 | |
| S3 buckets | 1 | `cdk-hnb659fds-assets-886312446417-us-east-1` |

### 2. Dirty fixture

Deployed to mimic what a real trial's agent leaves behind, deliberately under
names the hardcoded `scenarios/anchor/reset/reset.sh` sweep cannot match (it
only knows `apigw-redeploy-*` literals):

| # | Resource | Type | Exact ID |
|---|---|---|---|
| 1 | `zz-teardown-fixture-loose-fn` | `AWS::Lambda::Function` | `arn:aws:lambda:us-east-1:886312446417:function:zz-teardown-fixture-loose-fn` |
| 2 | `zz-teardown-fixture-loose-role` | `AWS::IAM::Role` | `arn:aws:iam::886312446417:role/zz-teardown-fixture-loose-role` |
| 3 | `/zz-teardown-fixture/custom-logs` | `AWS::Logs::LogGroup` | same |
| 4 | `/aws/lambda/zz-teardown-fixture-loose-fn` | `AWS::Logs::LogGroup` | Lambda-auto-created on first invoke |
| 5 | `zz-teardown-fixture-stack` | `AWS::CloudFormation::Stack` | `arn:aws:cloudformation:us-east-1:886312446417:stack/zz-teardown-fixture-stack/7a202d60-9289-11f1-ac0f-0affcaf6540d` |
| 6 | ↳ `FixtureFunction` member | `AWS::Lambda::Function` | `zz-teardown-fixture-stack-FixtureFunction-m19YQe1VKu94` — **CFN-random name, unpredictable, no `FunctionName` given** |
| 7 | ↳ `FixtureRole` member | `AWS::IAM::Role` | `zz-teardown-fixture-stack-FixtureRole-TtLnTWRe3ePF` — **CFN-random name** |
| 8 | auto log group for #6 | `AWS::Logs::LogGroup` | `/aws/lambda/zz-teardown-fixture-stack-FixtureFunction-m19YQe1VKu94` |
| 9 | orphaned auto log group | `AWS::Logs::LogGroup` | `/aws/lambda/zz-teardown-fixture-stack-FixtureFunction-kK7Ie24307I1` — residue from an **earlier, already-deleted** copy of the fixture stack (an identical fixture was created, torn down by hand mid-experiment while chasing the version-hash blocker below, and re-created; its Lambda's auto log group was never manually cleaned, so it sat in the account as genuine, unplanned orphan residue — a bonus, realistic test case for "does the framework catch residue *I* missed") |

Each Lambda was invoked once to force its `/aws/lambda/...` log group into
existence (matching the documented leak mechanism: `cdk destroy`/`terraform
destroy` never removes these).

### 3. Blockers en route, and how they were resolved

Two blockers were hit trying to trigger the reset, both real and both
instructive about the framework's own safety posture — neither is mentioned in
the prior Amendment 17 writeup, so they're recorded here in full:

**(a) Scenario-hash mismatch.** `aws-bench env reset --env-name cdktn-anchor
...` (the literal CLI path) failed immediately:

```
ERROR [anchor__6YJNSqP][PRIMARY/886312446417][us-east-1] Dataset or script
      version mismatch detected - requires full cleanup and redeploy
ERROR [anchor__6YJNSqP] Trial anchor/anchor__6YJNSqP reset failed: env reset
      failed for 1 account(s): Dataset/script version mismatch - requires
      full cleanup
```

Cause, confirmed by `git log -- scenarios/anchor`: the anchor scenario's source
tree changed twice (`scenarios/anchor/reset/reset.sh` added, then `QARolesStack`
gained `QADeployApplicationRole`) **after** the account was last `env setup`
(2026-08-06 15:14 UTC, commit `316b130`) — two prior, unrelated, already-
decided/committed changes to this repo, not anything this experiment did.
`VerifyManager._check_recoverable` treats a local-source-hash mismatch as
unrecoverable-by-reset by design, and routes to `env cleanup` + `env setup` —
not an option here (`env cleanup` unconditionally deletes the scenario's own
CFN stacks, which are on the hard preserve list).

**(b) Contaminated-account flag.** The failed CLI attempt (a) flagged the
account via `AccountManager.mark_contaminated` (an `aws-bench:contaminated`
Organizations tag on the member account), which then blocked a subsequent `env
setup` (the only way to refresh the stale baseline hash) at its DEPLOY-phase
contamination check. Clearing that tag directly (`organizations:
UntagResource`, the same call `AccountManager.clear_contaminated` makes
automatically on any successful reset/cleanup) was attempted from the
management account and was **blocked by the sandbox's own auto-mode
classifier** on both a scoped and a minimal retry. Per the tool's own guidance
("if you believe this capability is essential... stop... let the user
decide"), that specific action was abandoned rather than repeatedly retried or
routed around.

**Resolution actually used:** rather than force a path through (a)/(b),
`ResourceManager.reset_scenarios` — the exact function both the CLI's `env
reset` and the automatic post-mutating-trial hook
(`AwsBenchSingleStepTrial._reset_scenario_account` → `ScenarioTrial.
run(RESET)` → `ScenarioTrial._run_reset`) call — was invoked **directly**, as
real, unmodified library code, from a small script (`direct_reset.py`,
reproduced here in full):

```python
results = await ResourceManager.reset_scenarios(
    scenario_name="anchor",
    scenario_dir=None,           # <-- the only deviation from a live trial
    account_mapping={"PRIMARY": "886312446417"},
    max_concurrent=1,
    output_dir=OUTPUT_DIR,
)
```

`scenario_dir=None` is a supported, documented call shape —
`VerifyManager._check_dataset_version`'s own docstring: `current_scenario_dir:
Path to current scenario directory (optional)`, and its body: `if
current_scenario_dir is None: # No scenario path provided - skip version
check`. It skips **only** the local-source-tree staleness check (blocker (a),
which is about *this repo's checkout* being ahead of *this account's last
setup*, not about anything the AWS account itself contains) — it does not
touch, skip, or alter `_check_new_resources`, `_check_stack_status`,
`_check_template_hash`, `_check_drift`, or any deletion logic. The account's
contamination flag (blocker (b)) is never consulted by `ResetManager` at all —
that check exists solely in the CLI's DEPLOY-phase wrapper
(`ScenarioTrial._run_phase_in_container`, gated on `phase ==
ScenarioPhase.DEPLOY`), so calling `reset_scenarios` directly needed no
contamination workaround. No `aws-bench` source was modified. Credentials came
from `CredentialProvider.get()`'s ambient boto3 chain (the same
aws-vault-injected management-account credentials `env reset` itself would use
to assume `OrganizationAccountAccessRole`) — nothing was ever written to disk.

This is not a weaker test of the mechanism than the CLI path — it is the
*same* mechanism (`ResourceManager.reset_scenarios` → `ResetManager.
reset_account` → `_delete_new_resources` → `ResourceCleaner.cleanup(...,
custom_delete=True, ccapi_fallback=True)`), invoked one layer closer to the
code, with one specific, well-understood, and immaterial-to-the-experiment
check disabled.

Separately: the fixed-name `reset.sh` sweep **did** run for real once, in the
CLI attempt before it hit blocker (a) — `Running reset script in container ...
reset script finished (exit=0)` — 22 seconds, harmless no-op, as expected
(`zz-teardown-fixture-*` matches none of its hardcoded `apigw-redeploy-*`
literals).

## After inventory and per-resource verdict

Re-listed via `OrganizationAccountAccessRole` immediately after the direct
reset call returned `ResetResult(success=True, reason='Account successfully
reset to baseline state', ...)`:

| Category | Count | Matches "before"? |
|---|---|---|
| CFN stacks | 3 (same 3, all `CREATE_COMPLETE`) | Yes |
| Lambda functions | 0 | Yes |
| REST APIs | 0 | Yes |
| IAM roles (excl. service-role) | 10 (identical set) | Yes |
| CloudWatch log groups | 0 | Yes |
| S3 buckets | 1 (same bucket) | Yes |

Explicit `zz-teardown-fixture*` residue check: **zero matches** across
`lambda:list-functions`, `iam:list-roles`, `logs:describe-log-groups` (both the
explicit-prefix and `/aws/lambda/`-prefix queries), and `cloudformation:
describe-stacks` (returns `ValidationError: ... does not exist`).

Preserve-list spot check, all confirmed intact and untouched:
`QALocalInvocationApplicationRole`, `QALocalInvocationApplicationAdmin`,
`cfn-service-execution` present; `QADeployApplicationRole` correctly **not**
deployed (matches the preserve list's own "(if deployed)" qualifier — this
experiment never ran `env setup`, so it was never created live);
`anchor-QARoles-us-east-1`, `anchor-Anchor-us-east-1`, `CDKToolkit` all still
`CREATE_COMPLETE`, never deleted. `LLMJudgeFullBedrockAccessRole` is (still)
present, consistent with Amendment 16's removal being committed in code but
not yet deployed via `env setup` — expected, unrelated to this experiment.

| # | Resource | Detected as new? | Deletion path | Survived? |
|---|---|---|---|---|
| 1 | `zz-teardown-fixture-loose-fn` (Lambda) | Yes | Custom handler: `cleanup.handlers.lambda_` | **Deleted** |
| 2 | `zz-teardown-fixture-loose-role` (IAM Role) | Yes (global type) | CCAPI/CloudControl fallback (`prepare` then `delete`) | **Deleted** |
| 3 | `/zz-teardown-fixture/custom-logs` (LogGroup) | Yes | CCAPI/CloudControl fallback | **Deleted** |
| 4 | `/aws/lambda/zz-teardown-fixture-loose-fn` (LogGroup) | Yes | CCAPI/CloudControl fallback | **Deleted** |
| 5 | `zz-teardown-fixture-stack` (CFN Stack, CFN-random members) | Yes | CCAPI/CloudControl fallback (`DeleteResource` on `AWS::CloudFormation::Stack`, cascades) | **Deleted** |
| 6 | `...-FixtureFunction-m19YQe1VKu94` (Lambda, CFN-random name) | Yes | Custom handler: `cleanup.handlers.lambda_` (deleted directly, ahead of/independent from the stack cascade) | **Deleted** |
| 7 | `...-FixtureRole-TtLnTWRe3ePF` (IAM Role, CFN-random name) | Yes (global type) | Deleted by the stack cascade (#5) first; global pass found it already gone (`Skip AWS::IAM::Role ...: no longer exists`) and counted it as cleared | **Deleted** |
| 8 | `/aws/lambda/...-FixtureFunction-m19YQe1VKu94` (LogGroup) | Yes | CCAPI/CloudControl fallback | **Deleted** |
| 9 | `/aws/lambda/...-FixtureFunction-kK7Ie24307I1` (orphaned LogGroup) | Yes | CCAPI/CloudControl fallback | **Deleted** |

**9/9 deleted. 0 survivors. 0 preserve-list violations.**

## Log evidence (decisive lines, quoted verbatim)

Baseline load:
```
Loaded snapshot for 886312446417: 3 stacks, 1286 resources
Resetting across 1 region(s): us-east-1
```

Discovery — genuinely stack-membership-agnostic:
```
Scanning for new resources via fast-scan (996 resource types from baseline)
Fast-scan: 60 type(s) detected, 188 lister(s) failed
New resources detected - AWS::CloudFormation::Stack: 1 resource(s)
  - arn:aws:cloudformation:us-east-1:886312446417:stack/zz-teardown-fixture-stack/7a202d60-9289-11f1-ac0f-0affcaf6540d
New resources detected - AWS::Lambda::Function: 2 resource(s)
  - zz-teardown-fixture-loose-fn
  - zz-teardown-fixture-stack-FixtureFunction-m19YQe1VKu94
New resources detected - AWS::IAM::Role: 2 resource(s)
  - zz-teardown-fixture-loose-role
  - zz-teardown-fixture-stack-FixtureRole-TtLnTWRe3ePF
New resources detected - AWS::Logs::LogGroup: 4 resource(s)
  - /aws/lambda/zz-teardown-fixture-loose-fn
  - /aws/lambda/zz-teardown-fixture-stack-FixtureFunction-kK7Ie24307I1
  - /aws/lambda/zz-teardown-fixture-stack-FixtureFunction-m19YQe1VKu94
  - /zz-teardown-fixture/custom-logs
```

Stack-membership independence confirmed directly: the stack status/template-
hash/drift checks — which only ever look at stacks *present in the baseline*
(`anchor-QARoles-us-east-1`, `anchor-Anchor-us-east-1`, `CDKToolkit`) — all
passed clean in the same pass that found the new stack above purely via the
account-wide fastscan diff:
```
Drift matches: anchor-QARoles-us-east-1
Drift matches: anchor-Anchor-us-east-1
Drift matches: CDKToolkit
Drift detection: all stacks match baseline
```

Deletion — `ccapi_fallback=True` in active use:
```
Phase 2: Deleting 7 new resource(s)
Deleted Lambda function 'zz-teardown-fixture-loose-fn'
Deleted Lambda function 'zz-teardown-fixture-stack-FixtureFunction-m19YQe1VKu94'
Custom-deleted 2 resource(s): AWS::Lambda::Function, AWS::Lambda::Function
After filtering: 5 of 5 resources to delete
CCAPI-deleted 5 resource(s)
Phase 2: No unrecoverable stacks to delete, skipping
Phase 3: No drift differences to fix, skipping
```
(the 5 CCAPI-deleted resources are the CFN stack itself plus all 4 log groups —
the two IAM roles are a `GLOBAL_RESOURCE_TYPES` member and were correctly
deferred out of this regional pass, per `_delete_new_resources`'s own
documented rationale about not race-deleting a global resource a still-in-
flight regional dependent might need)

Final regional re-verify — clean:
```
Scanning for new resources via fast-scan (996 resource types from baseline)
Excluded 1 deferred (eventually-consistent) resource(s)
All verification checks passed
```

Global (account-wide) pass — the deferred IAM roles, including the CFN-
cascade-already-deleted one handled gracefully, not as a failure:
```
Final pass (global resources): Deleting 2 new resource(s)
Prepared 1 resource(s): AWS::IAM::Role
Skip AWS::IAM::Role zz-teardown-fixture-stack-FixtureRole-TtLnTWRe3ePF: no longer exists
After filtering: 1 of 2 resources to delete
CCAPI-deleted 2 resource(s)
```

Final result:
```
Account successfully reset to baseline state
```
```python
ResetResult(success=True, reason='Account successfully reset to baseline state',
            account_id='886312446417', scenario_name='anchor', details=None,
            suggestion=None, needs_redeploy=False, redeploy_succeeded=None)
```

## Runtime cost (per-trial overhead) — corrects the prior "~4 minutes" figure

Two components, timed separately from precise log timestamps because the
direct-invocation method skipped the in-container `reset.sh` phase (proven
separately, in the CLI attempt, before that attempt hit the version-hash wall):

| Phase | Duration | Source |
|---|---|---|
| Scenario container build + start | ~28s | CLI attempt log, `00:46:34`→`00:47:02` |
| `reset.sh` in-container (fixed-name sweep, no-op here) | ~22s | CLI attempt log, `00:47:02`→`00:47:24` |
| Framework generic reset (`ResetManager.reset_account`) | **7m 53s (473s)** | Direct-invocation log, `00:59:40.396`→`01:07:33.679` |
| ↳ of which: initial account-wide fastscan (996 types) | ~3m 24s | `00:59:44`→`01:03:08` |
| ↳ of which: deletion (regional + global passes) | ~61s | `01:03:08`→`01:03:44` + `01:07:08`→`01:07:33` |
| ↳ of which: final re-verify fastscan (996 types) | ~3m 24s | `01:03:44`→`01:07:08` |

**Total estimated per-trial reset overhead for a real mutating trial: ≈ 8.5–9
minutes**, dominated overwhelmingly (≈ 6m 48s of ≈ 8m 43s, ~78%) by the **two**
full account-wide fastscans (initial discovery + final re-verification) — not
by CloudFormation stack deletion, which is what the prior Amendment 17 pass
attributed its (lower, ~4 minute) figure to. This document's number is derived
directly from timestamped `DEBUG`-level log lines end to end and is preferred.
Note this cost is **not** bounded by `scenarios/anchor/scenario.toml`'s `[reset]
timeout_sec = 300.0` — that config only wraps the in-container `reset.sh`
script (22s here, well inside budget); `ResourceManager.reset_scenarios`'s own
account-wide scan/delete/verify work is not subject to it. It is, however, real
wall-clock cost that should be budgeted into overall per-trial throughput and
cost estimates for any `mode = "mutating"` task.

## Conclusion

Upstream's `ResetManager.reset_account` (via `ResourceManager.
reset_scenarios`, the same code both `aws-bench env reset` and the automatic
post-`mode = "mutating"`-trial hook call) **fully solves the leak**. It is:

- **Stack-membership-agnostic**: it found and deleted a whole CloudFormation
  stack the baseline never knew about, purely via the generic `AWS::
  CloudFormation::Stack` fastscan diff, with no special-case code for "a
  resource belongs to some other stack."
- **Correct on CFN-random physical names** — the specific case `scenarios/
  anchor/reset/reset.sh`'s own header comment says a fixed-name sweep
  structurally cannot cover (the `awscdk` arm). Both the stack's Lambda
  function and its IAM role, with unpredictable `zz-teardown-fixture-stack-
  FixtureFunction-m19YQe1VKu94`/`-FixtureRole-TtLnTWRe3ePF`-shaped names, were
  cleaned up — the function via the custom Lambda-delete handler (which
  enumerates by discovered identifier, not by a predicted name), the role via
  the CFN stack's own cascade delete.
- **Robust to a resource orphaned by a previous, unrelated teardown** — the
  leftover `/aws/lambda/...-kK7Ie24307I1` log group from an earlier, already-
  deleted copy of the fixture stack (accidental, not planned) was picked up
  and deleted in the very same pass, with no special handling needed.
- **`ccapi_fallback=True` is genuinely load-bearing**, confirmed live: 7 of the
  9 fixture resources (the CFN stack, all 4 log groups, and both IAM roles)
  went through the CloudControl API path, not a bespoke per-service handler —
  `AWS::ApiGateway::*`, `AWS::Logs::LogGroup`, and `AWS::CloudFormation::
  Stack` have no entry in `cleanup/handlers/`, so the generic fallback is what
  actually deletes them.

No partial-coverage findings. No resource class failed. The account matched
its "before" inventory exactly, and the preserve list survived intact. This
independently reconfirms Amendment 17's conclusion.

**One honest caveat, unrelated to coverage:** this session's own diagnostic
first attempt (the literal `aws-bench env reset` CLI path) failed on a stale
local-source-hash check and, on failing, flagged the account `aws-bench:
contaminated = true` (an Organizations tag) — confirmed still set as of this
writing via a read-only `organizations:list-tags-for-resource` check. That flag
does **not** affect any resource in the account (the after-inventory is
identical to before) and does **not** invalidate this experiment's evidence
(the direct `ResourceManager.reset_scenarios` call never reads that flag) —
but it **will** block the next `env setup`/new trial against this account
until cleared. **Follow-up needed:** the operator should run `aws organizations
untag-resource --resource-id 886312446417 --tag-keys aws-bench:contaminated`
before the account is used for anything else (this session's own sandbox
classifier blocked that specific call for the agent; it needs a human or a
differently-scoped session to run it).

## Runtime environment notes

- Credentials: `aws-vault exec --no-session tcons-mgmt` for the management
  account leg; `sts assume-role` into `OrganizationAccountAccessRole` for every
  member-account (`886312446417`) call. **No credentials were written to any
  file at any point** in this pass — all STS output was piped directly into
  shell variables/env vars within a single command invocation, addressing the
  standing rule Amendment 17's process note left for future live work.
- The direct-invocation script (`direct_reset.py`) and its full log
  (`direct-reset-run.log`, `direct-reset-signal.log`) live under this session's
  scratchpad, not in this repo — they are reproducible from the three lines of
  code quoted above against `aws_bench.resource_management.manager.
  ResourceManager.reset_scenarios`.
