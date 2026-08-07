# Teardown experiment: does the upstream framework reset clean a dirty account?

**Date:** 2026-08-08 · **Account:** `886312446417` (dedicated benchmark account) · **Region:** us-east-1

**Operator authorization (verbatim, 2026-08-08):** *"I authorize the scoped destructive test
in the dedicated account (teardown to test upstream framework reset solves the leak)."*

## Verdict

**Upstream's framework reset fully cleans the account, including the cases our hand-written
sweep cannot handle.** `scenarios/anchor/reset/reset.sh` is unnecessary and should be removed;
`docs/teardown-options.md`'s recommendation to prove option (b) before building anything was
correct, and **DECISIONS.md Amendments 14 and 15 reached the wrong conclusion** (see §4).

## 1. Method

The prior "reset leaks resources" findings were all produced by **hand-running
`scenarios/anchor/reset/reset.sh` outside a trial**. That script sweeps by hardcoded resource
names. The framework's own path — `ResourceManager.reset_scenarios` →
`ResetManager.reset_account` → baseline diff over the live CloudFormation type registry →
`ResourceCleaner(..., ccapi_fallback=True)` — had never been executed for this scenario.

This experiment invoked the framework path directly (in-process, through the runner's own
`ResetManager`) against a deliberately dirty account.

## 2. The dirty fixture

Chosen so that **no name-based sweep could succeed**: names outside `reset.sh`'s hardcoded
list, plus CloudFormation-generated physical names (the awscdk-arm case).

| Resource | Identifier | Why it was chosen |
|---|---|---|
| CloudFormation stack | `zz-teardown-fixture-stack` | Stack-level teardown; children get CFN-random names |
| Lambda (in stack) | `zz-teardown-fixture-stack-FixtureFunction-kK7Ie24307I1` | **CFN-random physical name** — unmatchable by any name sweep |
| Lambda (in stack, 2nd) | `zz-teardown-fixture-stack-FixtureFunction-m19YQe1VKu94` | Same class, second instance |
| IAM role (in stack) | `zz-teardown-fixture-stack-FixtureRole-TtLnTWRe3ePF` | **CFN-random physical name** |
| Lambda (loose) | `zz-teardown-fixture-loose-fn` | Agent-chosen name outside the hardcoded list |
| IAM role (loose) | `zz-teardown-fixture-loose-role` | Agent-chosen name outside the hardcoded list |
| Log group (auto) | `/aws/lambda/zz-teardown-fixture-loose-fn` | Auto-created by Lambda; **carries no tags** (this is why tag-based sweeping was rejected) |
| Log group (explicit) | `/zz-teardown-fixture/custom-logs` | Explicitly created |

## 3. Result

```
ResetResult(success=True,
            reason='Account successfully reset to baseline state',
            account_id='886312446417', scenario_name='anchor',
            needs_redeploy=False)
```

Every fixture resource was deleted. Cloud Control API operations observed in the run log:

```
"TypeName":"AWS::CloudFormation::Stack"  Operation: DELETE
   Identifier: arn:aws:cloudformation:us-east-1:886312446417:stack/zz-teardown-fixture-stack/7a202d60-…
"TypeName":"AWS::IAM::Role"              Identifier: zz-teardown-fixture-loose-role
"TypeName":"AWS::Logs::LogGroup"         Identifier: /aws/lambda/zz-teardown-fixture-loose-fn
                                         Identifier: /aws/lambda/zz-teardown-fixture-stack-FixtureFunction-kK7Ie24307I1
                                         Identifier: /aws/lambda/zz-teardown-fixture-stack-FixtureFunction-m19YQe1VKu94
                                         Identifier: /zz-teardown-fixture/custom-logs
```

**After-inventory (preserve-list intact, everything else gone):**

```
stacks:     anchor-QARoles-us-east-1  anchor-Anchor-us-east-1  CDKToolkit   (all CREATE_COMPLETE)
lambdas:    (none)
loggroups:  (none)
restapis:   (none)
roles:      cdk-hnb659fds-{cfn-exec,deploy,file-publishing,image-publishing,lookup}-role-…,
            cfn-service-execution, OrganizationAccountAccessRole,
            QALocalInvocationApplicationRole, QALocalInvocationApplicationAdmin,
            LLMJudgeFullBedrockAccessRole
```

`LLMJudgeFullBedrockAccessRole` is still present because its removal (Amendment 16) is
committed in code but not yet deployed via `env setup` — expected, not a reset failure.

**Benign error worth recording** (it looks alarming in the log but is correct behaviour): the
baseline diff lists both a stack and its child resources, so after the stack DELETE removed the
role, the individual role delete returned
`ResourceNotFoundException … The role with name zz-teardown-fixture-stack-FixtureRole-TtLnTWRe3ePF
cannot be found`. The reset still reported success. Anyone reading reset logs should expect
these 404s on stack-child resources.

**Runtime:** ~4 minutes wall-clock for the reset of this fixture set (dominated by CloudFormation
stack deletion). This is per-trial overhead for `mode = "mutating"` tasks and must be included in
runtime budgeting for `apigw-redeploy` and `iam-e2e-role`.

## 4. What this corrects

DECISIONS.md **Amendments 14 and 15** concluded that no deleter existed for our resource types,
reasoning from a missing API Gateway handler. That inference was wrong on two counts:

1. `ccapi_fallback=True` is the real delete path — Cloud Control API handles resource types that
   have no bespoke handler, which is why an unmodified framework deleted a Lambda, an IAM role,
   log groups and a CloudFormation stack here.
2. The evidence behind those amendments came from hand-running `reset.sh`, which is **not** the
   code path a real trial takes. The leak indicted our script, not the framework.

**Consequence:** `scenarios/anchor/reset/reset.sh`'s fixed-name sweep should be deleted rather
than extended. The Slice G decision to move cleanup responsibility off the agent and onto the
post-trial reset (so `live_check` has something to observe) is now **supported by evidence** —
the reset can, in fact, do the job.

## 5. Scope note

aws-nuke remains **parked** (operator decision, 2026-08-08) — no longer needed for the per-trial
path given this result. `docs/teardown-options.md` retains the analysis and the authorization
design should an operator-invoked backstop ever be wanted for a contaminated account.

## 6. Handling note (process, not result)

The run was executed with botocore DEBUG logging, so the raw run log contained
`X-Amz-Security-Token` / `Authorization` headers for every API call; a subagent also wrote
assume-role credentials to a scratch file. All such files were deleted, none reached the
repository or git history, and the sessions were 1-hour credentials scoped to this account.
**For future live work:** keep boto/botocore logging below DEBUG and pipe credentials directly
into the consuming process rather than materializing them.
