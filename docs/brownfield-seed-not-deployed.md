# The brownfield seed is never deployed — `named-resource-replacement` does not measure its own trap

**Status: CLOSED 2026-08-26 — resolved by `docs/design/single-step-seed-deploy.md`
(implemented 2026-08-25; `specs/SCHEMA.md` §2.7.1, `DECISIONS.md` Amendment 31)
and DISCHARGED by the first complete live brownfield row: three arms, zero
exceptions, every arm `seed_deployed` / live `pass` / idempotence `converged`,
every live check resolving `old_group_ids: []` against a security group and an
interface VPC endpoint that genuinely existed
(`jobs/live-brownfield-seed/2026-08-25__22-21-37` and `…/2026-08-26__08-54-19`).
Amendment 28 is ACCEPTED as of that row; this document no longer blocks
anything.** Found 2026-08-25, on the first live brownfield battery
(`jobs/rerun-named-resource-replacement/2026-08-25__01-43-17`, and the voided
`…__00-42-05` before it). Everything below is left as it was written — it is the
record of the defect, and the three rows it voided stay voided.

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

## What was decided (2026-08-25)

**Option 1.** `workspace_seed.deploy` (`specs/SCHEMA.md` §2.7.1) makes
`AwsBenchSingleStepTrial._prepare` deploy the seed for real, inside the agent
container, under the agent's own role, before the agent's first token — and then
prove it landed — three ways in `_prepare`, plus a **fourth** at verify time
that refuses to grade a trial whose seed script never ran at all (added by the
same-day adversarial review, `DECISIONS.md` Amendment 31 §10 finding M3) —
every one of which **aborts** the trial rather than scoring it 0.0. (A 0.0 is a measurement about the agent; a seed that never
deployed produced no measurement at all.) The full contract is
`docs/design/single-step-seed-deploy.md`; Options 2 and 3 are rejected and not
revisited.

The design required **no runner change at all** — the task-level `pre_invoke`
hook already ran unconditionally for any task carrying the file, which this
write-up did not know.

Two findings this write-up also did not have, both load-bearing and both fixed
in the same pass:

1. **The terraconstructs state path published in Amendment 28 §4 was wrong.**
   State does not live at `cdktf.out/stacks/<id>/terraform.tfstate`; `cdktn`
   installs a `LocalBackend` whose default path is
   ``path.join(process.cwd(), `terraform.${stackId}.tfstate`)`` — i.e.
   `/app/project/terraform.<workspace_id>.tfstate`, an absolute path baked into
   `cdk.tf.json` at synth time. That wrong path is the **whole** of the
   `not_verifiable` verdict this scenario's terraconstructs row returned despite
   an apply AWS itself confirmed: the probe failed, not the deploy. Corrected in
   `gen.py::IDEMPOTENCE_STATE_PROBE`, and recorded as an Amendment 28 §4
   correction.
2. **A deployed seed broke `hcl-raw`'s tier-0 outright.** That arm's
   `plan_command` had no `-refresh=false`, so the moment a `terraform.tfstate`
   exists the *offline* verifier plan refreshes through dummy credentials and
   dies (`Refreshing state... [id=vpc-05c33a26cbf19bef8]` / `PLAN FAILED`, in
   this very battery's `verifier/test-stdout.txt:42-46`). The hcl-raw 0.0 in the
   table below was read as an agent failure; it was the verifier failing on
   state the agent's own *successful* apply created. Any seed-deploy design that
   did not fix this would have scored every hcl-raw brownfield trial 0.0 before
   the agent was judged. The generator now hard-errors on it.

## Consequences now

* **Amendment 28 stays DRAFT.** Its promotion criterion is a first live
  brownfield run; this was not one. The mechanism above does not promote it —
  it makes that criterion **reachable for the first time**, and the same run
  promotes Amendment 31 alongside it.
* The three rows above must not enter `docs/live-results.md` as brownfield
  measurements, and must never be pooled into the brownfield stratum
  (Amendment 28 §6).
* Batch B (4 remaining brownfield scenarios) was **blocked on the same
  mechanism** — every one of them would inherit this defect, because every one
  of them assumes a deployed seed. It is unblocked as of 2026-08-25, and each
  inherits every rule in §2.7.1: its own `deploy` block, its own `live_asserts`
  with a `pins_catch`, and its own `-refresh=false`. All three are generator-
  enforced, not review-time conventions.
* The `ecs-swappiness` rows from the same battery are unaffected and valid:
  it is a static scenario with no live check and no seed.
