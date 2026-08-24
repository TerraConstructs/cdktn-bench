# The brownfield seed is never deployed — `named-resource-replacement` does not measure its own trap

**Status: OPEN. Blocks promoting DECISIONS.md Amendment 28 out of DRAFT.**
Found 2026-08-25, on the first live brownfield battery
(`jobs/rerun-named-resource-replacement/2026-08-25__01-43-17`, and the voided
`…__00-42-05` before it).

## The claim the scenario makes

`specs/named-resource-replacement.yaml`'s `workspace_seed.premise` tells the
agent, verbatim:

> This workspace holds the network configuration for one internal service: a
> small VPC with a single private subnet, a security group, and an interface
> VPC endpoint for AWS Systems Manager. **It is already deployed in this
> account.**

Amendment 28 defines the brownfield form the same way: the `entry_file` ships
"hand-authored, plan-green, **already-deployed** config instead of §2.4's empty
skeleton, and the prompt is a change request against it."

## What is actually true

Nothing deploys it.

* The spec declares no `pre_invoke` and no `pre_invoke.deploy_prior`. No
  `tasks/anchor/named-resource-replacement-*/pre_invoke/` directory exists.
  (`deploy_prior` is a MULTI-STEP facility, `SCHEMA.md` §2.6; this is a
  single-step spec.)
* Nothing under `scenarios/` mentions `internal-services` / `InternalServices`,
  so the anchor scenario's own deploy does not create it either.
* The account is reset to the anchor baseline before the trial. That baseline
  is three stacks — `anchor-QARoles`, `anchor-Anchor`, `CDKToolkit` — and no
  VPC, security group or interface endpoint belonging to this scenario.

So at the moment the agent starts, the workspace holds **config describing
infrastructure that does not exist**, with no state file backing it.

## Why that voids the measurement

The trap is a *replacement* trap. Renaming a security group that is pinned to a
literal name forces destroy-then-create, and the interface VPC endpoint holding
that group turns the destroy into a `DependencyViolation`. Every step of that
requires the group to already exist **in AWS and in state**.

With nothing deployed there is nothing to replace, so the trap cannot fire on
any arm. The scenario's own `seed_asserts` name the poison correctly
("THE POISON. The security group is pinned to a literal, operator-chosen
name … the property that turns the requested rename into a replacement") — but
a poison with no deployed resource to act on is inert.

Direct evidence from the run: terraconstructs' plan reports
`aws_vpc.InternalServices_16D8EF50 … will be created`. A brownfield workspace
would refresh that VPC, not create it.

## The live check cannot catch this — it passes for free

`live_check.py`'s discriminating assertion fails when a group named
`internal-services-ssm-endpoint` (the OLD name) **survives**. Its own docstring
is explicit that this is what makes the oracle "discriminating rather than
decorative": an agent whose apply died half-way satisfies assertion 1 on a
retry-until-it-sticks approach "only if the old group is genuinely gone".

If the old group **never existed**, that assertion is satisfied vacuously. The
oracle reports `pass` while proving nothing about the behaviour it was written
to catch — the same vacuous-satisfaction defect the
`s3-notification-authoritative-singleton` rounds kept finding in IAM condition
operators (`…IfExists`, `ForAllValues:`), one layer up.

## What the three rows actually show

Recorded so the numbers are not mistaken for measurements later. **None of
these is a valid brownfield row.**

| arm | reward | tier0/1 | live_check | idempotence | reading |
|---|---|---|---|---|---|
| awscdk | 1.0 | PASS | pass | converged | LIKELY a greenfield deploy satisfying a vacuous live check. Not established — not fully traced. |
| hcl-raw | 0.0 | PLAN FAILED | pass | converged | Verifier plan shows `Refreshing state... [id=vpc-05c33a26cbf19bef8]`, so state existed BY THEN — the agent built the infra during its own run. Greenfield-then-rename, not brownfield. |
| terraconstructs | 0.0 | PASS | pass | not_verifiable | Deployed real resources (SG + endpoint confirmed in AWS) but no `terraform.tfstate` at the path the idempotence tier expects; gating downgraded 1.0 → 0.0. |

The awscdk/terraconstructs split is itself suspicious and probably an artifact
of where each toolchain keeps state: CloudFormation keeps it in AWS, so a CDK
arm needs no local state to look coherent, while both TF-shaped arms depend on
a local `terraform.tfstate` that nothing seeded.

## Options (not decided)

1. **Deploy the seed for real before the agent phase.** Truest to the form, and
   the only option under which the trap actually fires. Needs a single-step
   equivalent of `pre_invoke.deploy_prior`, credentialed, plus state placed
   where each arm's toolchain expects it — which is exactly the cross-arm
   asymmetry above, and the hard part.
2. **Reclassify the scenario as greenfield-then-rename** and rewrite the prompt
   and oracle to measure that instead. Cheap, honest, and measures something
   real — but it is NOT the brownfield form, and Amendment 28 would still have
   no live proof.
3. **Withdraw the scenario** until the seeding mechanism exists, and promote
   Amendment 28 on a different brownfield scenario built seed-first.

## Consequences now

* **Amendment 28 stays DRAFT.** Its promotion criterion is a first live
  brownfield run; this was not one.
* The three rows above must not enter `docs/live-results.md` as brownfield
  measurements, and must never be pooled into the brownfield stratum
  (Amendment 28 §6).
* Batch B (4 remaining brownfield scenarios) is **blocked on the same
  mechanism** — every one of them would inherit this defect, because every one
  of them assumes a deployed seed.
* The `ecs-swappiness` rows from the same battery are unaffected and valid:
  it is a static scenario with no live check and no seed.
