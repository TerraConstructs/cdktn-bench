# Teardown options for the benchmark account, and an authorization design

Design recon; nothing implemented. Companion reading: `docs/slice-g-recon.md` §4,
`DECISIONS.md` Amendments 14 ("B2 fix") and 15 ("Finding 3"),
`scenarios/anchor/reset/reset.sh`.

Paths are absolute across three repos: `/Users/vincentsmet/cdk/cdktn-bench` (this
repo), `/Users/vincentsmet/cdk/aws-bench` (the runner — not ours to edit; its
`AGENTS.md:85` marks "modifying AWS provisioning, IAM, or teardown/cleanup logic" as
ask-first), and `/Users/vincentsmet/cdk/untrusted/aws-nuke` (third party, read as
data only — nothing from it was built or run for this document).

---

## 0. The failure, stated precisely

`scenarios/anchor/reset/reset.sh:55-62` sweeps by hardcoded names: REST API `apigw-redeploy-api`, Lambdas `apigw-redeploy-{hello,version}`, role `apigw-redeploy-lambda-exec`, three log groups. But the task instruction (`specs/apigw-redeploy.yaml`, `instruction.shared_body`) mandates **exactly one** of them — "a REST API named EXACTLY `apigw-redeploy-api`". Lambda names, the execution role name and the log-group names are never required of the agent. On the `awscdk` arm CloudFormation assigns physical names itself; the repo's own reference solution says so at `tasks/anchor/apigw-redeploy-awscdk/solution/solve.sh:236-244` ("CDK's auto-generated function names carry an unpredictable hash suffix") and cleans up by *prefix* instead. Meanwhile the spec deliberately tells the agent not to clean up ("Do NOT delete the REST API, the Lambda functions, their execution role...").

So the sweep is not merely incomplete — it is structurally incapable of covering an arm whose names it cannot predict. That was the stated intent all along (`reset.sh` calls itself "defense in depth"), and `DECISIONS.md:3385-3392` records the real open question: whether the framework's generic sweeper covers these types was "genuinely unknown either way". §3(b) answers it.

---

## 1. What aws-nuke is

`github.com/ekristen/aws-nuke/v3` (`go.mod:1`), at `v3.66.0` +6 commits (HEAD
`bfe693f`). Maintained fork of the archived `rebuy-de/aws-nuke`; `README.md:60-66`
gives the fork rationale, `README.md:68-73` records that the engine was extracted
into `github.com/ekristen/libnuke`, pinned at `v1.3.0` (`go.mod:47`). Releases are
automated semantic-release (`.releaserc.yml`) and dense — `v3.63.0…v3.63.4`,
`v3.64.0…v3.64.4`, `v3.65.0`, `v3.66.0` in quick succession — and cosign-signed
(`.goreleaser.yml:76-89`, `artifacts: all`), verifiable against the repo-root
`cosign.pub`.

**Caveat that matters for authorization:** this tree holds the CLI shell, AWS glue,
and ~747 per-resource Lister/Remove files under `resources/`. The run loop, filter
engine, registry and roughly half the safety checks live in `libnuke`, an ordinary
module dependency that is **not vendored here** (`pkg/commands/nuke/nuke.go:17-21`;
no `vendor/`). Verify those claims against libnuke at the pinned version, not this
tree.

**Flow** (`pkg/commands/nuke/nuke.go`): `main.go:12-19` blank-imports commands and all
of `resources/` for `init()` side effects, each calling `registry.Register(&registry.Registration{Name, Scope, Resource, Lister, DependsOn, Settings})` (e.g. `resources/iam-role.go:28-44`). `execute()` then builds `libnuke.Parameters` from flags (`:59-78`), parses config (`:84-92`), discovers the account via STS `GetCallerIdentity` + IAM `ListAccountAliases` (`pkg/awsutil/account.go:51-106`), instantiates the engine (`:125`), registers the validate (`:132-134`) and prompt (`:137-138`) handlers, resolves includes/excludes across CLI → global → account (`:161-179`), registers one scanner per region (`:213-244`), and hands off to `n.Run(ctx)` (`:247`). Scan → filter → queue → delete and the multi-pass retry all run inside libnuke; resources cooperate via sentinel errors `ErrWaitResource` (`resources/iam-role.go:84`) and `ErrHoldResource` (`resources/cloudformation-stack.go:327`).

### Safety mechanisms and the code implementing each

| Mechanism | Implementation |
|---|---|
| Dry-run default; deleting needs `--no-dry-run` | flag `pkg/commands/nuke/nuke.go:278-281` → `Parameters.NoDryRun` (`:63`); `docs/warning.md:10-11` |
| **Empty blocklist is itself an error** | `libnuke@v1.3.0 pkg/config/config.go:109-121`: `if !c.HasBlocklist() { return errors.ErrNoBlocklistDefined }`; also `docs/config.md:74` |
| Account in `blocklist:` → abort | same fn: `if c.InBlocklist(accountID) { return errors.ErrBlocklistAccount }` |
| **Account must be named under `accounts:`** | same fn: `if _, ok := c.Accounts[accountID]; !ok { return errors.ErrAccountNotConfigured }` — strongest property here: an unnamed account fails closed, no override flag |
| Account must have an IAM alias | `pkg/config/config.go:118-122` |
| Alias must not contain a blocklisted term; `"prod"` injected by default | `pkg/config/config.go:83-85` (default term added in `Load()`), enforced `:124-131` |
| `--no-alias-check` insufficient alone | `pkg/config/config.go:110-116` — bypasses only if the ID is also in `bypass-alias-check-accounts` (`:57,91-99`); else warns and still checks |
| Type-the-alias confirmation, twice | `pkg/nuke/prompt.go:32-38`; `docs/warning.md:12-13` |
| `--force`/`--no-prompt` bypass, with mandatory delay | flag `:282-286`; bypass `pkg/nuke/prompt.go:27-30`, sleeping `--prompt-delay` seconds (default 10, min 3 via `common.CheckRealInt`, `:287-293`) |
| Config file mandatory and must exist | `:253-258` (`Action: common.CheckFilePath`) |
| Service-linked and SSO roles auto-excluded | `resources/iam-role.go:61-69`; SSO has **no** override |

**No org-awareness.** No `organizations:DescribeOrganization` call, no
management-account detection anywhere in the tree. aws-nuke cannot tell a management
account from a sandbox — the blocklist is the only thing between it and either. That
single fact drives §4.

Note the *anti*-safety knobs: `settings.<Type>.DisableDeletionProtection` (resolved
`pkg/config/config.go:139-178`) lets it strip CloudFormation termination protection
(`resources/cloudformation-stack.go:273-291`) and RDS/EC2/ELBv2 protection. Any
config we commit must leave `settings:` unset.

**Config format** (`docs/config.md:9-28`): `blocklist`, `blocklist-terms`,
`no-blocklist-terms-default`, `regions`,
`accounts.<id>.{presets,filters,resource-types}`, top-level
`resource-types.{includes,excludes,cloud-control}`, `presets`, `settings`. Filters
are **exclusions from deletion** — a match means *keep*. Types
(`docs/config-filtering.md:92-101`): `exact` (default), `contains`, `glob`, `regex`,
`dateOlderThan`, `dateOlderThanNow`, each taking `property:` (default `Name`) and
`invert:`. Filters within a type are OR'd (`:11-13`); AND-ing needs the experimental
`--feature-flag filter-groups`. `__global__` is a pseudo-type prepended to every
type (`:15-33`). Includes intersect across CLI → global → account; an exclude at any
level removes a type outright (`:443-446`).

---

## 2. Fitness for our scenarios

**Coverage is not the problem.** Every type our specs create has a resource:
`apigateway-restapis.go`, `apigatewayv2-apis.go`; `lambda-function.go`,
`lambda-layers.go`, `lambda-event-source-mapping.go`; `iam-role.go`,
`iam-role-policy.go`, `iam-role-policy-attachments.go`, `iam-policy.go`;
`cloudwatchlogs-loggroup.go`; `cloudformation-stack.go`, `-stackset.go`;
`ecs-{clusters,services,task-definition}.go`; `sfn-state-machine.go`;
`s3-bucket.go`, `s3-object.go`. CloudFormation handling is careful: `DELETE_FAILED`
retries with `RetainResources` for whatever will not delete
(`resources/cloudformation-stack.go:354-389`, bounded by
`CloudformationMaxDeleteAttempt = 3`, `:32`); nested stacks return
`ErrHoldResource("waiting for parent stack")` until the parent is gone (`:320-329`);
termination-protected stacks are **not** force-deleted unless
`DisableDeletionProtection` is explicitly set (`:273-291`).

**What must be preserved** — verified by read-only listing of `886312446417`
(us-east-1), 2026-08-07:

- Stacks `anchor-QARoles-us-east-1`, `anchor-Anchor-us-east-1`, `CDKToolkit`.
- Roles `OrganizationAccountAccessRole`, `cfn-service-execution`,
  `QALocalInvocationApplicationRole`, `QALocalInvocationApplicationAdmin`,
  `LLMJudgeFullBedrockAccessRole`, and five
  `cdk-hnb659fds-{cfn-exec,deploy,file-publishing,image-publishing,lookup}-role-886312446417-us-east-1`.
  (Six `AWSServiceRoleFor*` roles also exist; `resources/iam-role.go:61-69` excludes
  those automatically.)
- Managed policy `S3VectorsReadOnlyAccess-886312446417-us-east-1` (from
  `scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts:28-49`). The
  `CDKTo-FileP-*`/`CDKTo-Image-*` objects are **inline** role policies, not managed —
  they surface as `IAMRolePolicy`, keyed by role.
- Bucket `cdk-hnb659fds-assets-886312446417-us-east-1`; ECR repo
  `cdk-hnb659fds-container-assets-886312446417-us-east-1`.
- SSM parameters `/cdk-bootstrap/hnb659fds/version` and
  `/cdktn-bench/anchor-Anchor-us-east-1/anchor`.

**Two blockers found while writing the config:**

1. **The account has no IAM alias** — `list-account-aliases` returns empty, so
   `pkg/config/config.go:118-122` would refuse to run at all. Fixable once
   (`create-account-alias`), and it is a *feature*: the alias becomes a second,
   out-of-band assertion about which account we are in, and must not contain `prod`.
2. **`ECRRepository` cannot be filtered by name.** Its `Properties()`
   (`resources/ecr-repository.go:87-95`) sets only `CreatedTime` and tags — no
   `Name` — while `String()` is `"Repository: <name>"` (`:106-108`). Since the
   default filter property is `Name` (`docs/config-filtering.md:251-254`), a
   plausible name filter matches nothing and the CDK bootstrap ECR repo is
   destroyed. Exclude the whole type. This is exactly why a preserve-list must be a
   reviewed artifact validated against dry-run output rather than reasoning.

### The config that preserves exactly the above

```yaml
# ops/teardown/nuke-anchor.yaml — reviewed, committed, never agent-generated.
blocklist:
  - "489592802338"   # terraconstructs-org — AWS Organizations MANAGEMENT account
  - "694710432912"   # singaporewaketools  — production website account
regions:
  - global
  - us-east-1        # the only region any cdktn-bench scenario deploys to

resource-types:
  excludes:
    - ECRRepository  # cannot be name-filtered; see blocker 2
    - IAMUser        # nothing in this benchmark creates IAM users
    - IAMUserAccessKey
    - IAMSAMLProvider
    - IAMOpenIDConnectProvider

accounts:
  "886312446417":    # cdktn-bench — the ONLY account this config may touch
    filters:
      CloudFormationStack:
        - "anchor-QARoles-us-east-1"
        - "anchor-Anchor-us-east-1"
        - "CDKToolkit"
      IAMRole:
        - "OrganizationAccountAccessRole"
        - "cfn-service-execution"
        - "QALocalInvocationApplicationRole"
        - "QALocalInvocationApplicationAdmin"
        - "LLMJudgeFullBedrockAccessRole"
        - {type: glob, value: "cdk-hnb659fds-*-role-886312446417-us-east-1"}
      IAMRolePolicy:
        - {type: glob, property: "role:RoleName", value: "cdk-hnb659fds-*"}
      IAMRolePolicyAttachment:
        - {type: glob,  property: RoleName, value: "cdk-hnb659fds-*"}
        - {type: glob,  property: RoleName, value: "QALocalInvocationApplication*"}
        - {type: exact, property: RoleName, value: "LLMJudgeFullBedrockAccessRole"}
        - {type: exact, property: RoleName, value: "cfn-service-execution"}
        - {type: exact, property: RoleName, value: "OrganizationAccountAccessRole"}
      IAMPolicy:
        - "S3VectorsReadOnlyAccess-886312446417-us-east-1"
      S3Bucket:
        - "cdk-hnb659fds-assets-886312446417-us-east-1"
      S3Object:
        - {type: glob, property: Bucket, value: "cdk-hnb659fds-assets-*"}
      SSMParameter:
        - "/cdk-bootstrap/hnb659fds/version"
        - "/cdktn-bench/anchor-Anchor-us-east-1/anchor"
```

Every value is a fact verified by read-only listing, not a guess. Note what is
absent: no `settings:` (no protection stripping), no `bypass-alias-check-accounts`,
no `no-blocklist-terms-default`. The destructive scope is a two-account blocklist
plus a one-account allowlist — both literal strings a human reads once.

---

## 3. Options

### (a) aws-nuke from the host/runner with the config above

Deletes everything unfiltered, account-wide, with real CFN dependency handling —
highest completeness here. Costs: a third-party Go binary in the trusted path
(mitigated by cosign verification); half the safety logic in an unvendored
dependency; and a preserve-list that drifts by hand — if `QARolesStack` grows a
fourth role, the next run silently deletes it and the symptom is a broken scenario,
not an error.

### (b) The reset the runner already has — the important one

`DECISIONS.md:3385-3392` left this "genuinely unknown". It is now known.

`AwsScenarioTrial.run` calls `_reset_scenario_account()` after any `ConcurrencyMode.MUTATING` trial (`aws_bench/task/aws_trial.py:103-146`) — and our generated task **does** set it (`tasks/anchor/apigw-redeploy-awscdk/task.toml:23`, `mode = "mutating"`). That reaches `ResourceManager.reset_scenarios` (`aws_bench/resource_management/manager.py:301-357`), which assumes `OrganizationAccountAccessRole` (`aws_bench/account_management/constants.py:11`) and calls `ResetManager.reset_account` (`aws_bench/resource_management/reset/manager.py:71-178`). Per region (`:180-271`): verify → **delete new resources** → delete unrecoverable stacks → restore drifted stacks → re-verify and fail if anything survives.

The load-bearing phase is `_delete_new_resources` (`reset/manager.py:285-325`), handing the diff to `ResourceCleaner.cleanup(..., custom_delete=True, ccapi_fallback=True)` (`:360-366`). Amendment 14's `cleanup/handlers/` citations were wrong and Amendment 15 correctly flagged that (`DECISIONS.md:2930-2948`) — but both missed that `ccapi_fallback=True` *is* the generic delete path. The absence of a bespoke API-Gateway handler is not the absence of a deleter.

Discovery is genuinely generic. The baseline snapshot scans the **full public CloudFormation type registry**, resolved live via `cloudformation:list_types(Type="RESOURCE", Visibility="PUBLIC")` (`aws_bench/resource_management/ccapi/type_registry.py:59-79`), used as the default type universe by `FastScanManager.get_scannable_types` (`fastscan/manager.py:75-79`). Enumeration uses native per-service boto3 calls, **account/region-wide and completely stack-membership-agnostic**: `apigateway:GetRestApis` (`fastscan/listers/simple_listers.py:107-110`), `lambda:ListFunctions` (`:4695-4701`), `logs:DescribeLogGroups` (`:5007-5045`), and a custom `iam:ListRoles` pager excluding only `/aws-service-role/` (`fastscan/listers/custom_listers.py:209-218`, registered `:3030`). A Lambda made by raw `aws lambda create-function` is enumerated identically to a CDK-managed one. `VerifyManager._check_new_resources` (`verify/manager.py:143-212`) then set-diffs against the POST_SETUP baseline over types present *or scanned-and-empty* at baseline (`:165-170`) — and a pristine anchor account puts Lambda/IAM/Logs/APIGW squarely in the scanned-and-empty bucket, exactly the inclusion rule needed.

**Conclusion: the runner's existing mechanism is designed for precisely our failure and, on the source, covers it — including the `awscdk` arm's randomly-named resources, which no name-based sweep can ever cover.** It is also the only option needing no new authorization, because it already runs unattended today.

Honest gaps, all code-visible: types failing to enumerate in *either* scan are silently dropped from the diff (`verify/comparators.py:192-201`), so a throttle becomes a false negative; the AWS-managed ownership probe fails **open** (keeps, not deletes) for KMS keys and ENIs on error (`verify/ownership.py:100-131`); deletes are best-effort with the final re-verify as the only gate; and it diffs against POST_SETUP, not pristine — the fuller sweep is the heavier `env cleanup`. Upstream neither overclaims nor hides this: `docs/getting-started.md:288` says leakage is possible, `:336` says "if you see it, it's a bug we want to fix", and `docs/datasets-development.md:127` concedes the machinery "contains some assumptions on the usage of CDK or CloudFormation".

**Critically, this path has never actually run for `apigw-redeploy`.** Every live proof in `DECISIONS.md` (Amendment 15 Findings 1 and 3, `:3200`, `:3353-3383`) was a *hand-run* of `solve.sh`/`reset.sh` under `aws-vault`, outside a real trial. The observed leak is evidence that the fixed-name sweep is inadequate — which we knew — and is **not** evidence that the framework reset fails. Nobody has yet run `aws-bench env verify` against a deliberately dirty account and read the result.

### (c) Tag-based sweep via `resourcegroupstaggingapi`

Needs an instruction-mandated tag the agent may forget or apply inconsistently across three toolchains, and which **cannot** apply to resources it does not create — the `/aws/lambda/...` log groups AWS auto-creates on first invocation carry no tags, and those are among the resources actually observed leaking. It also adds a benchmark-integrity smell: a tagging requirement the agent is graded on obeying for reasons unrelated to the task. Cheap to build, unsound exactly where our leaks are.

### (d) Org-side automation: StackSet / EventBridge Lambda in the management account

Feasible — a Lambda in `489592802338` assuming `OrganizationAccountAccessRole` into `886312446417` on a schedule or trial-completion event. But it **moves risk rather than reducing it.** The deleting principal now lives in the management account holding a credential that reaches *every* member account including `694710432912`. Blast radius goes **up**: today a misconfigured host script has whatever the operator's aws-vault session has; under (d) a misconfigured Lambda has org-wide administrative reach, continuously, unattended, unwatched. Auditability improves (management-account CloudTrail) and it removes the "operator's laptop is the trusted path" problem, but review burden rises to four surfaces (trust policy, event rule, Lambda code, StackSet targets) and the failure mode is silent and repeating. Not a first step; a reasonable end state once (b) is proven.

### (e) Account recycling — close and re-vend

Strongest completeness guarantee: a fresh account cannot leak, and the only option whose safety does not depend on a preserve-list being correct. But closure has a 90-day suspension window before the ID is released, creation is rate-limited, and `deploy/deploy.sh` would need a full `cdk bootstrap` + `cdk deploy --all` per recycle (~10+ min; `scenario.toml` allows 900s). Not viable per-trial; viable as quarterly hygiene.

### Scoring

| | (a) aws-nuke | (b) upstream reset | (c) tag sweep | (d) org-side Lambda | (e) recycle |
|---|---|---|---|---|---|
| Completeness | High | High (source); **unproven live** | Low | = payload | Total |
| Blast-radius containment | Good (fails closed) | Good (one account by construction) | Excellent | **Poor** (org-wide, unattended) | Excellent |
| Auditability | Good (dry-run diff in git) | Weak (logs only, no diff artifact) | Good | Excellent | Excellent |
| Operational cost | Medium (binary + list drift) | **Zero — already runs** | Low | High | High |
| Ease of narrow authorization | Good (one wrapper, one config) | **N/A — needs none** | Good | Poor (4 surfaces) | N/A |

### Recommendation

**Prove (b) before building anything.** The runner already contains a
CFN-registry-generic, stack-agnostic, delete-capable reset that fires automatically
on `mode = "mutating"`, and it is the only candidate that handles the `awscdk` arm's
unpredictable names. Proving it costs one dirty-account experiment; not proving it
risks bolting a nuke onto a runner that already does the job.

**Then adopt (a) as an operator-invoked backstop, not a per-trial step.** Its real
job is the case (b) escalates on: a failed reset that flags the account contaminated
(`aws_bench/scenario/trial.py:899-918`, `account_management/constants.py:31`), where
upstream's own answer is `env cleanup` + `env setup`. aws-nuke is a faster, more
thorough version of that recovery, run by a human who decided to run it. Do **not**
wire it into the per-trial path — a destructive tool on an unattended loop is how
(d)'s failure mode arrives by the back door.

Do not build (c). Defer (d). Keep (e) as periodic hygiene.

---

## 4. The authorization design

The goal is not to get past a classifier. It is to make the destructive scope a
**property of code a human reviewed once**, so no agent decision at run time can
widen it. Refusing to let an agent author broad pattern-based deletion is correct;
the fix is to remove the agent from the scope decision entirely. Five mechanisms,
each failing closed, composed.

**1. Scope lives in a committed config, never in an argument.**
`ops/teardown/nuke-anchor.yaml` (§2) is the only place an account ID or preserve
entry appears; reviewing it *is* reviewing the blast radius. Because
`libnuke@v1.3.0 pkg/config/config.go:109-121` refuses any account absent from
`accounts:`, this file is the enforcement boundary, not documentation.

**2. A wrapper whose only parameter is a scenario id** — it cannot be asked to
target another account because the account never appears on its command line. This
mirrors the existing `scripts/run-bench.sh` convention.

```
ops/teardown/
  nuke-anchor.yaml            # §2 config. Account IDs live ONLY here.
  README.md                   # what this is, who approved it, how to re-verify
scripts/
  reset-scenario-account.sh   # the only entry point; argv is a scenario id
  lib/verify-nuke-binary.sh   # cosign verify against ops/teardown/cosign.pub
```

`scripts/reset-scenario-account.sh <scenario-id>` must, in order, aborting on any
mismatch: (1) map id → config path from a literal `case`, unknown id exits 2;
(2) `sts get-caller-identity` and assert the account equals the config's — refusing
outright if the caller is the management account; (3) `iam list-account-aliases` and
assert the alias equals the expected literal, the out-of-band check that catches a
shell pointed at the wrong account; (4) run **dry-run first**, teeing to
`jobs/<ts>/teardown-dryrun.txt`; (5) assert the dry-run names **zero** preserve-list
entries — this is what catches preserve-list drift, aborting instead of deleting a
newly added QA role; (6) only then re-run `--no-dry-run --no-prompt --prompt-delay
10`, teeing to `jobs/<ts>/teardown-apply.txt`. Steps 4-5 are the audit artifact: a
recorded diff, reviewable, produced *before* anything is destroyed.

**3. Fail-closed blocklist.** `blocklist:` names `489592802338` (management) and
`694710432912` (production). Since an empty blocklist is itself an error
(`ErrNoBlocklistDefined`), a truncated or corrupted config cannot degrade into an
unguarded run — it degrades into a crash.

**4. Alias match required.** The account has **no** alias today, so enabling this is
a deliberate one-time operator act (`aws iam create-account-alias --account-alias
cdktn-bench`). It must not contain `prod` (`pkg/config/config.go:83-85,124-131`).
Do not set `bypass-alias-check-accounts`.

**5. A permission rule naming the wrapper, plus a deny closing every other route.**
In `/Users/vincentsmet/cdk/cdktn-bench/.claude/settings.json` — project scope, so it
travels with the repo and is reviewed in the same PR as the config (this repo has no
`.claude/` directory today; this creates one):

```json
{
  "permissions": {
    "allow": ["Bash(./scripts/reset-scenario-account.sh:*)"],
    "deny":  ["Bash(*aws-nuke*)"]
  }
}
```

Four properties make this work, confirmed against
`code.claude.com/docs/en/permissions.md` and `settings.md`:

- **`Bash(foo:*)` is a prefix match with a word boundary** — `:*` is an equivalent spelling of trailing ` *`, recognized only at the end of a pattern. The allow rule matches `./scripts/reset-scenario-account.sh anchor` but **not** `bash ./scripts/reset-scenario-account.sh anchor`, a different literal prefix. Only `timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`, `builtin` and zsh's `noglob` are stripped before matching — a built-in, non-configurable list that does not include `bash`/`sh`. Pick one invocation form and document it in `ops/teardown/README.md`.
- **Wildcards may appear mid-string.** `Bash(*aws-nuke*)` matches any command containing `aws-nuke` — `/usr/local/bin/aws-nuke`, `sudo aws-nuke`, `$(which aws-nuke)` — closing the direct-invocation routes a prefix rule leaves open, while catching neither the wrapper (whose name contains no such substring) nor the wrapper's *internal* call to the binary, which is not a Bash tool call. That is precisely the funnel we want.
- **`deny` beats `ask` beats `allow`**, and specificity does not reorder them, so the two rules cannot conflict into an accidental permit. Note `allow`/`deny`/`ask` arrays are **concatenated and deduplicated across scopes**, not replaced — a user-level rule stays in force alongside this file; run `/permissions` after deploying to see which file each rule loaded from.
- **`deny` and `ask` survive auto-mode.** Under `defaultMode: "bypassPermissions"` or `--dangerously-skip-permissions`, prompts are skipped *except* those forced by explicit `ask` rules, and `deny` removes the action regardless of mode. This is the direct answer to "how do I make this safe in auto-mode": the `allow` rule buys nothing there, but the `deny` still holds — and if a human decision is wanted on the destructive step even in auto-mode, move the wrapper from `allow` to `ask`, since a content-scoped `ask` prompts even under bypass mode and under sandboxed auto-allow.

For a hard gate rather than a guardrail, a `PreToolUse` hook is strictly stronger: it receives the full command as JSON on stdin (`.tool_input.command`) and applies arbitrary logic.

```json
{ "hooks": { "PreToolUse": [ { "matcher": "Bash",
  "hooks": [ { "type": "command", "command": "/abs/path/ops/teardown/guard.sh" } ] } ] } }
```

The blocking contract is **`exit 2`** — stderr goes back to the model as the error,
stdout is ignored. Exit 1 is treated as *non-blocking* and the command proceeds;
that is the trap worth knowing. Alternatively exit 0 with
`{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
"permissionDecisionReason":"..."}}`. Do not rely on the handler's `if` pre-filter as
the boundary — it fails **open** when a Bash command cannot be parsed. Put the check
in the script. Organizationally,
`permissions.disableBypassPermissionsMode: "disable"` (ideally in managed settings,
where it cannot be overridden) removes `--dangerously-skip-permissions` entirely.

Mechanism 5 is defense in depth. The real boundary is mechanism 1 —
`ErrAccountNotConfigured` — because it is enforced by the tool being run, not by the
harness running it, and has no override flag.

---

## 5. Risks and failure modes

**Wrong account targeted.** Three independent checks must fail together: the wrapper's caller-identity assertion, the alias assertion, and `ErrAccountNotConfigured`. The last has no override flag and is the one to rely on. Residual risk is a config edit changing the account ID — the risk lives entirely in review of one file. Say so in `ops/teardown/README.md` and require a second reviewer for it.

**Preserve-list drift is the most likely real incident.** Adding a role to `qa_roles_stack.ts` without updating `nuke-anchor.yaml` means the next teardown deletes it, and the symptom appears on the *following* run, far from the cause. Mitigation: the dry-run assertion (§4.2 step 5) plus a CI check that every `roleName:` literal in `qa_roles_stack.ts` appears in the config's `IAMRole` filters.

**Filters that silently do not match.** The `ECRRepository` finding (§2) proves this is not hypothetical — a plausible name filter matches nothing and destroys the bootstrap repo. Every preserve entry must be validated against real dry-run output, never reasoning; adding one requires re-running the dry-run.

**Supply chain.** A third-party binary in the destructive path with half its safety logic unvendored. Pin the version, verify the cosign signature (`cosign.pub`, `.goreleaser.yml:76-89`) inside the wrapper, record the verified digest in `ops/teardown/README.md`.

**`--no-prompt` removes the human.** Once passed, the alias-typing gate (`pkg/nuke/prompt.go:32-38`) is gone and only `--prompt-delay` remains. That is the intended trade for automation, but it means the dry-run assertion now does the work the human used to. If that assertion is ever weakened, re-review this option from scratch.

**Doing nothing also fails.** If (b) does not work and no backstop exists, every mutating trial leaks, and a failed reset flags the account contaminated (`aws_bench/scenario/trial.py:899-918`), bricking the shared anchor account for unrelated scenarios — the risk `docs/slice-g-recon.md` §4 already warned about.

### Evidence a reviewer should demand before enabling any of this

1. **The (b) experiment, first.** Deploy the leaking fixture under names the
   fixed-name sweep cannot match (the `awscdk` arm's own hashed names are the
   natural choice), run a **real mutating trial** — not a hand-run `solve.sh` — and
   capture `aws-bench env verify` before and after, the `ResetManager` log, and a
   resource listing. If the account comes back clean, (a) is a backstop and nothing
   needs per-trial authorization. Publish the transcript in `DECISIONS.md` the way
   Amendment 15 published its own.
2. A dry-run transcript from the proposed config showing every preserve-list entry
   **absent** from "would remove" and the leaked resources **present**.
3. Proof the blocklist works: a dry-run with the config's account temporarily set to
   a blocklisted ID, showing the abort.
4. Proof the alias gate works: a dry-run before the alias is set, showing the
   "doesn't have an alias" refusal.
5. Cosign verification output for the pinned binary.
6. The wrapper's source read line by line, with attention to whether any argument
   can reach the `--config` flag.

Items 3 and 4 matter more than they look: they are the only evidence that the
fail-closed properties this design rests on are real in *our* environment, rather
than merely present in upstream's source.
