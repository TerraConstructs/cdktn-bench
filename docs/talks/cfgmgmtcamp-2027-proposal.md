# Talk proposal — CfgMgmtCamp Ghent 2027

Format: standard presentation, 45 min + 5 Q&A. Track: Main. Draft; numbers
are the corpus state on 2026-09-21 and are re-read before submission.

## Title

Falsifiable by construction: building a benchmark for AI-written
infrastructure code

## Abstract (short, for the programme)

"Does a typed construct library make an AI agent better at infrastructure
code than raw HCL?" is easy to ask and easy to answer wrongly. This talk is
about the second half. cdktn-bench measures Claude Code writing the same
infrastructure ticket in AWS CDK, raw Terraform HCL and a CDKTF-shaped
construct library, and grades it in a real AWS account. The result is less
interesting than the method: pre-registered hypotheses, an oracle for every
scenario that must be shown to fail on a planted mistake before it may pass a
correct answer, a metric that is never pooled across things that measure
different tasks, and a decision log of 43 amendments recording every time the
design turned out to be wrong. Everything shown is open source.

## Description (for reviewers)

The benchmark exists to put empirical weight behind a claim in the CDK
Terrain roadmap: that intent-level typed constructs are a more token-efficient
substrate for AI-assisted infrastructure authoring than resource-level HCL.
The talk is not the result. It is how a small team, working mostly through
agentic tooling, built a measurement they could trust, and what broke on the
way.

**1. Pre-registration before data (10 min).** Three falsifiable hypotheses
(the bold one: an un-tuned CDK arm beats a tuned HCL arm), a fixed factorial
design, a headline metric (output tokens until the oracle first passes,
right-censored, always paired with success rate), and an explicit "what would
falsify this" paragraph, all locked before any trial ran. Every later change
is an amendment with a rationale, and an amendment that touches the harness
returns to DRAFT until a live run proves it. Why this discipline matters
more, not less, when the authors of the benchmark are also the authors of the
thing being benchmarked.

**2. The oracle problem: wrong output with no error (15 min).** A scenario is
a YAML spec: a ticket the agent reads, a set of structural assertions over the
synthesized artifact (a CloudFormation template or a `terraform show -json`
plan), Rego policies for cross-resource facts, and, where behaviour is the
point, a live check against the deployed account. Three techniques carried the
weight:

* *Falsifiability gates.* No oracle ships until a hand-written correct
  solution scores 1.0 on every arm and a hand-written broken solution, one per
  planted catch, scores 0.0 for the right reason at the predicted tier. A
  catch that can only be seen live must prove, mechanically, that no static
  tier can separate it.
* *Three-valued verdicts.* An assertion is held, contradicted, or
  unresolvable. "The path could not be asked" is never a pass and never a
  fail. This one rule caught more real defects than anything else, and it is
  the reason two off-the-shelf policy engines were evaluated and declined.
* *Prompt parity and identity hygiene.* The ticket byte-identical across
  arms except one language line; a deny list that fails generation if the
  pitfall's vocabulary leaks into anything the agent can see; scenario ids
  that name the trap while workspace names name only the goal.

Worked examples from the corpus: an API Gateway stage whose omitted burst
limit is applied as zero (the plan showed it, the human-readable plan did
not); an ECR repository that applies and passes every check and then refuses
to be destroyed (which forced a teardown grading tier); a security-group
rename that Terraform can only do destroy-first (which needed the agent's
long-running command to survive the harness).

**3. Measuring on live AWS without lying to yourself (10 min).** Why mocks
were excluded (they return false greens on exactly the value-rejection class
under study); four sharded sandbox accounts with exclusive admission for
mutating trials and a framework reset that is independent of the agent's own
teardown; transient AWS errors retried and, when exhausted, voiding the row
rather than scoring it; a result row that must carry its scenario form and,
soon, its agent access mode, so a directory mixing brownfield and greenfield
refuses to print a headline.

**4. What the benchmark got wrong, in order (10 min).** A brownfield seed the
prompt claimed was deployed and never was, so a replacement trap had nothing
to replace and the live oracle passed vacuously. A harness flag that silently
backgrounded a 16-minute deploy and killed it at turn end. A blueprint whose
central premise (an attribute absent from the plan) was falsified by the
blueprint's own "plan both spellings first" rule. A Rego translation of the
static tier that passed every parity gate and was rejected anyway, because
five readable jq lines had become three hundred unreadable ones. Each is an
amendment, each has a live promotion run, and the talk closes on the
question the corpus can now ask next: the same ticket with plan-only access
versus apply-and-iterate access, per arm.

Attendees leave with a checklist for grading AI-written infrastructure code
that they can apply to their own tooling, whether or not they care about the
CDK-versus-HCL question, and with the repository.

## Audience and prerequisites

Practitioners who write or review IaC and are being asked whether AI agents
can. Familiarity with Terraform or CloudFormation helps; no benchmark or ML
background needed. No vendor product; Claude Code is the fixed harness, not
the subject.

## Notes to reviewers

Everything is open source (repository link in the submission). Numbers shown
will be the corpus at talk time; the method sections do not depend on which
arm wins. The speaker built the benchmark and maintains the construct library
it tests, which is disclosed on the first slide and is the reason section 1
exists.

## Corpus facts to refresh before submission

| fact | value (2026-09-21) |
|---|---|
| scenarios | 20 (12 greenfield, 4 brownfield, 1 multi-step; 3 arms) |
| oracle tiers | static JSONPath (117 asserts, 9 ops), Rego / cfn-guard, live check, idempotence, teardown |
| amendments in the decision log | 43 (5 not adopted or retired) |
| offline gates per scenario | falsifiability, grading-proof, check-paths, parity, tier0-parity |
| live promotion runs | one per harness-changing amendment, recorded in `docs/live-results.md` |
| sandbox accounts | 4 shards, exclusive admission for mutating trials |
