# Amendment 32 promotion battery — trajectory-level findings

Material: `jobs/amend32-promotion/2026-08-27__21-38-21` (ecs-swappiness, 3 arms × k=2, read-only) and
`jobs/amend32-promotion/2026-08-27__21-50-09` (apigw-redeploy multi-step + named-resource-replacement
brownfield, 3 arms × k=2, mutating). All 24 `agent/claude-code.txt` stream-json transcripts were rendered
turn-by-turn and read in full; "A<n>" below is the n-th assistant message in that transcript (this is also
the "num_turns" that `docs/live-results.md` reports — see §6.10 for the two competing definitions).
Comparison runs: `jobs/claude-sonnet-5/2026-08-20__17-16-22`, `jobs/live-brownfield-seed/*`, `jobs/g-live-*`.

Every trial is n=2 per cell. Where a claim rests on one or two trajectories it is marked **(n=2)**; where a
pattern is visible in every trial of a scenario it is marked **(6/6)** etc.

---

## 0. The 18 trials in one table

| trial | turns | out tok | 1st entry-file write | 1st toolchain run | node_modules reads | tool errors | sleep s | wall s | reward |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| ecs awscdk j9GYNqu | 20 | 4,245 | A6 | A8 | 1 | 0 | 0 | 83 | 1.0 |
| ecs awscdk oAF8eeB | 22 | 3,815 | A7 | A9 | 3 | 0 | 0 | 55 | 1.0 |
| ecs hcl 8grne9A | 9 | 1,244 | A4 | A5 | 0 | 0 | 0 | 24 | **0.0** |
| ecs hcl AbZbQXi | 10 | 1,158 | A4 | A6 | 0 | 0 | 0 | 27 | **0.0** |
| ecs tcons oirNgaR | 44 | 6,099 | A28 | A34 | 16 | 1 | 0 | 112 | 1.0 |
| ecs tcons twcAkP7 | 25 | 3,947 | A15 | A17 | 6 | 2 | 0 | 69 | 1.0 |
| apigw awscdk fkvo6HF s1/s2 | 28/28 | 4,007/4,440 | A14/A8 | A16/A10 | 0/1 | 2/0 | 0/20 | 148/244 | 1.0/1.0 |
| apigw awscdk jDwLKPF s1/s2 | 27/38 | 4,318/5,996 | A5/A8 | A7/A10 | 0/1 | 2/1 | 0/25 | 132/214 | 1.0/1.0 |
| apigw hcl AiV6ppW s1/s2 | 19/30 | 6,964/6,516 | A8/A4 | A9/A6 | 0/0 | 0/0 | 0/17 | 126/137 | 1.0/1.0 |
| apigw hcl fvL6ddy s1/s2 | 33/31 | 8,293/5,488 | A6/A6 | A9/A10 | 0/0 | 0/0 | 0/65 | 131/171 | 1.0/1.0 |
| apigw tcons 8tyeqwP s1/s2 | 62/54 | 9,164/6,876 | A22/A13 | A24/A16 | 13/5 | 4/0 | 0/65 | 181/209 | 1.0/1.0 |
| apigw tcons YudrrS4 s1/s2 | 81/49 | 12,622/6,224 | A48/A18 | A50/A21 | 28/9 | 2/0 | 0/15 | 209/151 | 1.0/1.0 |
| nrr awscdk R3UCRfD | 16 | 2,514 | A6 | A8 | 0 | 1 | 0 | 100 | 1.0 |
| nrr awscdk Ttym8Ju | 18 | 3,103 | A4 | A9 | 0 | 1 | 0 | 192 | 1.0 |
| nrr hcl hXhAAe4 | 17 | 4,502 | A6 | A9 | 0 | 1 | 0 | 93 | 1.0 |
| nrr hcl bmocEVR | 56 | 10,487 | A6 | A8 | 0 | 4 | 3 | **766** | 1.0 |
| nrr tcons SSXBd6K | 59 | 10,937 | A7 | A11 | 9 | 0 | 0 | **1,156** | 1.0 |
| nrr tcons saaxzSo | 75 | 11,024 | A6 | A13 | 12 | 1 | 150 | **1,169** | 1.0 |

"tool errors" = tool_results flagged `is_error` (includes the agent's own malformed calls, see §6.8).
"1st toolchain run" = first `terraform init/plan/apply`, `cdk synth/deploy`, `cdktn synth/deploy`, `tsc`, or `npm run build/synth`.

---

## 1. Task & scenario effectiveness

### 1.1 ecs-swappiness (greenfield, read-only)

**Discriminates on reward, cleanly and reproducibly.** hcl-raw 0.0/0.0, both L2 arms 1.0/1.0 (6/6 agree with
the 2026-08-20 row). The trap is genuinely exercised on every arm, but through *two different channels*,
which the §3 law does not currently distinguish:

- **hcl-raw wrote the wrong answer confidently and never doubted it.** 8grne9A: A4 `Edit` writes
  `linuxParameters = { swappiness = 42 }` (no `maxSwap`), A5 `terraform init`, A6 `validate && plan` — the
  plan output prints `linuxParameters = { swappiness = 42 }` back at the agent, which reads as confirmation
  ("Validated and plans cleanly … `linuxParameters.swappiness = 42`", A7). AbZbQXi is the same in 10 turns
  and **never ran `terraform plan` at all** — only `init` + `validate` (A6). `docs/live-results.md`'s line
  "hcl_raw's `terraform plan` was green against the real account on the agent's first command" is true of
  8grne9A only. Neither hcl trial read any documentation, used the `aws` CLI, or considered `maxSwap`.
  Transparency here is actively misleading: the plan echoes exactly what was sent, which is exactly what
  AWS will discard.
- **awscdk wrote the same wrong answer first, and the L2 corrected it after the fact.** Both awscdk trials'
  first write omits `maxSwap` (j9GYNqu A6, oAF8eeB A7). Neither read `linux-parameters.d.ts` before writing.
  The correction came from the agent *inspecting its own synthesized template* and finding `LinuxParameters:
  {Capabilities: {}}` with no `Swappiness` (j9GYNqu A10, oAF8eeB A11), then grepping the construct source
  (A12 / A14) and adding `maxSwap` (A15 / A18). The L2's silent-drop line
  (`this.swappiness = props.maxSwap ? props.swappiness : undefined`) mirrors the ECS API's behaviour at
  synth time, so the trap became *observable offline* — but only because the agent looked. Had either agent
  trusted `npm run synth`'s exit code and stopped, tier-0 `swappiness-value-correct` would have scored it 0.0
  like hcl. **The awscdk win on this scenario is conditional on the agent's self-verification habit**, not on
  the abstraction alone (n=2 — both agents happened to verify; §5 P2 proposes measuring how often that holds).
  Note the difference in *understanding*: j9GYNqu's writeup calls it "a quirk in this CDK version … maxSwap
  … arbitrary but consistent … purely to unlock that emission" (A14, agent-output.txt); oAF8eeB read the
  JSDoc (A16) and quotes "If a value is not specified for maxSwap then this parameter is ignored". Same
  artifact, different depth; the oracle cannot see the difference and shouldn't try to.
- **terraconstructs received the knowledge before writing, both times.** twcAkP7 A6–A7 `Read`
  `ec2-task-definition.d.ts` and `linux-parameters.d.ts`, then A15's first write already carries
  `// swappiness is only honored when maxSwap is also set.` oirNgaR A11 grepped `validateProps` in
  `linux-parameters.js`, saw line 55's silent drop, and wrote `maxSwap` at A28. This is the read-before-write
  delivery ROADMAP §3 finding 3 describes, replicated 2/2 on this arm and 0/2 on awscdk.

**Instruction as a ticket.** Works — one goal, one number. One sentence matters more than it looks: "This is
a definition-only task: nothing needs to be deployed, started, or attached to a cluster or service." It is
parity-neutral, but it removes the only path by which an hcl-raw agent could have discovered the trap
(`register-task-definition` + `describe-task-definition` shows `linuxParameters: {}`, ROADMAP §3). The
scenario therefore measures *prior knowledge + what the toolchain's own feedback loop can reveal*, not the
agent's ability to verify against the service. That is a legitimate design choice, but it should be stated
in the spec's `oracle.intent`, because it is why hcl-raw fails "cheap" here and would plausibly not fail
under an oracle-authority-inverted (M5) design that invited a live probe.

**Oracle vacuity / reviewer disagreement.** None found on the passing side: both L2 arms emit
`MaxSwap`+`Swappiness` at the right nesting, `RequiresCompatibilities: [EC2]`, one container. A human reviewer
would not question any accepted artifact. On the failing side the verifier is opaque: `test-stdout.txt`
prints `== tier-1: OPA/Rego ==` followed by nothing, then `tier1_status=FAIL` (8grne9A, AbZbQXi) — see §6.6.
Minor: the L2 arms create an IAM task role the ticket never asked for (tcons plan "2 to add", awscdk
`TaskRoleArn`), which the oracle ignores; correct, since the ticket says "definition-only", not
"exactly one resource".

### 1.2 apigw-redeploy (multi-step, mutating)

**Does not discriminate on reward (6/6 arms × attempts = 1.0 on both steps); discriminates on cost.** The
planted catches did not fire on any trial:

- `stale-deployment-no-triggers` / `triggers-incomplete-hash` (hcl-raw only): both hcl step-1 solutions
  wrote `triggers = { redeployment = sha1(jsonencode([...ids...])) }`, complete `depends_on`, **and**
  `lifecycle { create_before_destroy = true }` on `aws_api_gateway_deployment` unprompted (AiV6ppW A8,
  fvL6ddy A6), and both step-2 solutions extended the hash list to the new resources (AiV6ppW A4 — one
  `Edit` covering resources, hash, and depends_on; fvL6ddy A6–A8 three edits). AiV6ppW's step-2 writeup even
  explains the mechanism ("so that `terraform apply` produces a new deployment revision"). The model *knows*
  this idiom; the "operator forgot to extend the hash" catch is a tail-knowledge trap that this model treats
  as head knowledge. The live-tier catch is therefore unfalsified but also unexercised (n=2 per arm).
- `deployment-missing-integration-dependency`: neither L2 arm left the L2 path (no `CfnDeployment`,
  no L1 `Deployment`); CDK's logical-id salting is visible in the transcripts
  (`ApigwRedeployApiDeploymentF6C10091c282610f…` in step 1 → `…701c85a0…` in step 2, fkvo6HF).

Cost ordering awscdk (8.4k/10.3k) < hcl (13.5k/13.8k) < tcons (16.0k/18.8k) is stable across both attempts,
but see §3.2: since the trap never fired, the awscdk–hcl gap is *compression* (about 40 lines of TypeScript vs
15 HCL resources ≈ 200 lines), not encoded experience.

**What actually consumed the day-2 step on every arm: an API Gateway edge-propagation blip.** 6/6 step-2
trials got `403 {"message":"Missing Authentication Token"}` on `/status` immediately after a successful
deploy, while `/hello` and `/version` returned 200: fkvo6HF A14 (resolved by A22 after ~100 s of polling),
jDwLKPF A14 (test-invoke-method 200 at A25, cache-busting query 200 at A29, plain 200 by A31), AiV6ppW A10
(200 at A23), fvL6ddy A14 (200 at A25 after `sleep 60`), 8tyeqwP A36 (200 at A47 after `sleep 60`), YudrrS4
A33 (200 at A43, third 10-s poll). Between 8 and 16 turns per step-2 trial — up to 40% of a step's turns —
went into diagnosing a property of EDGE-optimised REST APIs that has nothing to do with the arm. Every agent
diagnosed it correctly and none tore anything down, but the cost is charged to tokens-to-green on every arm
roughly equally (~600–1,500 output tokens), so it is noise, not bias. The verifier's `live_check.py` polls
180 s, so it would have passed even for an agent that stopped at the first 403 — good, but it means the
oracle would have *accepted a trajectory that ended with the agent believing its route was broken*.

**Instruction as a ticket.** Step 1 and step 2 are clean tickets with no foreshadowing; no agent showed any
sign of anticipating `/status`. Three problems with the "standing constraints" block:

1. **Arm-asymmetric construct naming in `language_line`.** awscdk is told "(apigateway.RestApi,
   LambdaIntegration)" in step 1 and "(…, MockIntegration)" in step 2; terraconstructs is told only "using
   terraconstructs (TypeScript) L2 constructs"; hcl nothing. The tcons agents paid to discover what awscdk
   was handed: 8tyeqwP step 2 A8 `grep -ril "mock" node_modules/terraconstructs/lib/aws/compute/`, A9–A11
   read `mock.d.ts`, `method.d.ts`, `integration.d.ts`; YudrrS4 step 2 A8–A16 the same. That is a
   vocabulary hint given to one L2 arm and not the other — a parity defect under CLAUDE.md's own rule that
   only the target-language line may differ, and the line is supposed to name the *language*, not the
   constructs. (Fix: drop the parenthetical on awscdk, or give tcons the equivalent `compute.RestApi,
   compute.LambdaIntegration, compute.MockIntegration`. Dropping is the non-coaching option.)
2. **The IAM-path "environment constraint" appears to be unenforced** ("this account's deploy credentials
   only permit creating and passing roles under that path"). The agent runs as
   `QALocalInvocationApplicationAdmin` (AdministratorAccess, Amendment 24); nothing under `scenarios/`,
   `cdktn_bench/` or `gates/` references `/cdktn-bench-task/` (DECISIONS.md lines 3529–3775 describe the
   old scoped role, since retired). Both tcons step-1 trials spent turns on it: the terraconstructs
   `RestApi` L2 creates an account-level CloudWatch role *without a path* by default; 8tyeqwP A35–A39 and
   YudrrS4 A61–A64 found `Api_CloudWatchRole … path= None` in the synthesized JSON and set
   `cloudWatchRole: false`. awscdk never faced this because its `cdk.json` ships
   `"@aws-cdk/aws-apigateway:disableCloudWatchRole": true` — an equipping difference baked into the
   workspace, not an L2 difference (§2.1). If the constraint is real, it should be enforced (then an
   un-noticed CloudWatch role would fail the deploy — a genuine, fair catch); if it is not, the sentence is
   fiction that taxed one arm. Verify against the live role policy before the next battery.
3. The block names the other arms' syntax ("on a Terraform `aws_iam_role`, or … on a CDK/terraconstructs
   `iam.Role`"). Parity-forced and harmless, but an awscdk agent reading "terraconstructs" is a small leak
   of the experiment's existence.

**Oracle acceptance a reviewer might question.** (a) 8tyeqwP step 1's handlers return plain-text bodies
`'hello'` / `'v1'` rather than JSON — accepted because bodies aren't graded; fine per the ticket ("exact
response content is not graded"). (b) fvL6ddy grants `lambda_permission` with `source_arn = ".../*/*"`
(any method, any path) where AiV6ppW scoped to `/*/GET/hello`; not graded, and arguably the awscdk L2 emits
the same broad permission — a reviewer would let it pass. (c) jDwLKPF and both tcons trials share one
execution role across both functions; the ticket says "each backed by its own Lambda function", which is
satisfied; roles are unconstrained. (d) Tier-0 `mock-integration-wired` is `contains MOCK` over all
integrations — any MOCK anywhere passes; the live check is what actually proves `/status`. No vacuity
observed, but the static tier is nearly decorative on this step.

### 1.3 named-resource-replacement (brownfield, mutating)

**Does not discriminate on reward (6/6 = 1.0, idempotence `converged` 6/6, live check pass 6/6);
discriminates on cost and on whether the trap fires.** Trap-fire by arm:

| arm | attempt | trap fired? | how it was resolved |
|---|---|---|---|
| awscdk R3UCRfD / Ttym8Ju | both | impossible by construction (CFN create-then-delete; deploy log A10: "Requested update requires the creation of a new physical resource; hence creating one") | one-line edit, 16–18 turns |
| hcl hXhAAe4 | 1 | **no** — A5 states before editing: "renaming forces SG replacement, and AWS won't let the old SG be deleted while still attached"; A6 adds `create_before_destroy` | 17 turns, 93 s |
| hcl bmocEVR | 2 | **yes** — A8 plan shows `-/+ destroy and then create`, agent applies anyway (A10); apply hangs in "Still destroying…" for 9+ min | TaskStop A22, stale-lock saga A24–A40, fix A31, re-apply A44; 56 turns, 766 s |
| tcons SSXBd6K | 1 | **yes** — A11 `cdktn diff` shows `-/+ destroy and then create`; A12 (thinking) and deploys anyway A13; hangs ~15 min | escape-hatch discovery A36–A47; `(findChild("Resource") as TerraformResource).lifecycle = {createBeforeDestroy: true}` A50; 59 turns, 1,156 s |
| tcons saaxzSo | 2 | **yes** — deploys at A13 without diffing; hangs ~15 min | escape-hatch discovery A37–A51; `defaultChild.addOverride("lifecycle", …)` A53 → tsc errors A55 → cast to `TerraformResource` A60–A61; 75 turns, 1,169 s |

Two things a static reading of the spec misses:

- **The live consequence is a hang, not an error.** The AWS provider retries `DependencyViolation` on
  security-group delete for its full delete timeout; no trial ever *saw* the string `DependencyViolation`
  from Terraform — the diagnosis came from the agent's own knowledge while watching "Still destroying…
  09m39s elapsed" (bmocEVR A17, saaxzSo A29, SSXBd6K A27). Combined with Claude Code's Bash tool timeout
  (120 s default; 300 s in saaxzSo A13), every hung apply was backgrounded and the agent spent 5–9 turns on
  `ToolSearch`/`TaskOutput`/`sleep` waiting (bmocEVR A12–A20, saaxzSo A15–A27, SSXBd6K A15–A25). Turn
  counts on the TF arms are inflated by this waiting, not by authoring; output tokens much less so.
- **Two of three TF-arm trials that saw the destroy-first plan deployed anyway** (bmocEVR A8→A10, SSXBd6K
  A11→A13). `-/+` in a plan is the exact signal; the model did not act on it until the apply hung. hXhAAe4,
  which knew, checked for `+/-` explicitly ("Plan confirms `+/-` create-before-destroy replacement", A10).
  That is a read-the-plan behaviour worth measuring (M1 blast-radius column would capture it).

**The terraconstructs L2 obstructs rather than encodes here.** Its `SecurityGroup` exposes no `lifecycle`
passthrough (spec `arms.terraconstructs.reason` says so), so both tcons agents had to (a) discover that
the L2 hides the L1 (`grep createBeforeDestroy … security-group.js`, saaxzSo A37; SSXBd6K A36–A41), (b) find
the construct's `"Resource"` child, (c) discover `addOverride`/`lifecycle` on cdktn's `TerraformResource`,
and (d) fight the type system (`'defaultChild' is possibly 'undefined'`, `Property 'addOverride' does not
exist on type 'IConstruct'`, saaxzSo A55). ~15 turns each. This is the mirror image of ecs-swappiness: the
abstraction removed the knob the fix needs. The pre-32 tcons trial KJM6cJY used the same escape hatch
(`(defaultChild as TerraformResource).lifecycle = {createBeforeDestroy: true}`), so escape-hatch incidence
on this arm is 3/3 by construction — which makes `docs/live-results.md`'s sentence "with the tier fixed,
the escape hatch disappeared" wrong (§6.5).

**Instruction as a ticket.** Good: one change, one acceptance criterion ("still reachable on 443 from
inside the VPC … not from anywhere else"). Every agent verified that criterion live with
`describe-security-groups`/`describe-vpc-endpoints` (6/6) — the ticket's phrasing drove real verification.

**Oracle vs reviewer.** (a) bmocEVR and saaxzSo left the `Name` tag / L2-generated tag at the *old* name
(`tags.Name = "internal-services-ssm-endpoint"`, bmocEVR A31 diff context); hXhAAe4 updated the tag (A7).
A reviewer would flag the stale tag as an incomplete rename; the oracle ignores tags. Not a vacuity, but a
reminder that "rename" is graded on one attribute. (b) `interface-endpoint-still-declares-security-groups`
on awscdk is the documented weaker twin; nothing in the two awscdk trials would have tripped the stronger
form either. (c) Idempotence converged on all six — including saaxzSo/SSXBd6K, whose lifecycle override
lives only in synthesized JSON; `terraform show -json` does not emit `lifecycle`, so the tier is correct
to plan rather than diff config. (d) The seed proof (`old-group-is-live`, `endpoint-holds-the-old-group`)
passed pre-agent on all six, so the live check's "no old group remains" was never vacuous.

---

## 2. Workspace / setup effectiveness

### 2.1 awscdk

For the agent: `package.json` scripts (`build`, `synth`) and the baked `tsconfig.tsbuildinfo` meant zero
setup friction; every trial compiled on the first `npm run build`. `cdk.json`'s feature-flag context is
**hidden equipping**: `@aws-cdk/aws-apigateway:disableCloudWatchRole: true` is why awscdk never met the
CloudWatch-role/IAM-path problem that cost both tcons trials (§1.2). That is not the L2's doing; it is a
39-line context block the generator ships. The comparison "awscdk vs terraconstructs on apigw" currently
compares *L2 + curated feature flags* against *L2 alone*.

Against the agent:

- **`bin/app.ts`'s comment is a harness-vocabulary leak that induced behaviour.** It says "synth-only
  oracle tiers", "live `cdk deploy` uses the CDKToolkit bootstrap roles (`cdk-hnb659fds-*`, created by
  deploy.sh's `cdk bootstrap`)", "The mutation agent runs as `QALocalInvocationApplicationAdmin`
  (AdministratorAccess, DECISIONS.md Amendment 24)", "arm parity", "hcl-raw arm". fkvo6HF read it at A2 and
  then ran `find / -maxdepth 4 -iname "deploy.sh"` (A10) and checked CDKToolkit in two regions (A12);
  jDwLKPF checked CDKToolkit at A16. It does not name any trap, but "oracle", "tiers", "graded" in
  `environment/` contradict CLAUDE.md's "never mention grading, tiers, or the verifier", and it tells the
  agent it is in a benchmark with other arms. Every awscdk trial read this file (8/8 steps).
- **`AWS_REGION` is not staged.** `env | grep -i aws` shows `AWS_PROFILE=PRIMARY` and empty
  `AWS_ACCESS_KEY_ID`/`AWS_REGION`; `~/.aws/config` does not exist (fkvo6HF A8, jDwLKPF A11). `cdk deploy`
  coped (it defaults), but every `aws` CLI verification call failed with `NoRegion` until the agent exported
  it: jDwLKPF s1 A22, s2 A20; R3UCRfD A12; Ttym8Ju A13; also hXhAAe4 A13 and saaxzSo A34 on the TF arms. 1–2
  wasted turns per trial. The TF arms' toolchains have the region in `provider.tf`/`main.ts`, so this tax is
  paid mainly on verification, not deploy, but it is paid on every arm that verifies with the CLI. Staging
  `AWS_REGION=us-east-1` alongside `AWS_PROFILE` is an environment property (the account is single-region
  by SCP, fkvo6HF A12), not coaching.
- **`npm run synth` prints the full template to stdout**; agents `tail -50` it and get 50 lines of
  `Fn::Equals: Ref: AWS::Region` partition conditions (j9GYNqu A8, oAF8eeB A9, fkvo6HF A17, R3UCRfD A8),
  then re-run with `--json`/inspect the file. Cache tokens, not output tokens; one extra turn.
- **The bootstrap-status probe is legitimate but paid.** Both apigw awscdk trials spent 2–4 turns confirming
  `CDKToolkit` exists (fkvo6HF A6–A12, jDwLKPF A9–A16). The TF arms have no equivalent question. This is
  the arm's own nature (CDK needs a bootstrap), so it is measurement, not harness cost.

### 2.2 hcl-raw

For the agent: `provider.tf` with a pinned provider and hard-coded region is the cleanest bootstrap of the
three — on ecs and NRR the first toolchain command ran green with zero setup turns (8grne9A A5, hXhAAe4 A9).
The pre-32 `TF_VAR_cdktn_bench_live`/`UnrecognizedClientException` tax (2 hits per step in qSyGeRD) is
gone: grep of all 24 transcripts for `InvalidClientTokenId|UnrecognizedClientException|mock-sts|mock-sfn|
cdktn_bench_live|CDKTN_BENCH_LIVE` is empty, and no `aws-unavailable` marker was written.

Against the agent:

- **The image has no `zip`, and the provider mirror has no `hashicorp/archive`.** Both apigw hcl trials hit
  `zip: command not found` (AiV6ppW A4, fvL6ddy A17) and fell back to `python3 -c "import zipfile…"`.
  fvL6ddy additionally wrote the idiomatic `data "archive_file"` (A6), added a `terraform { required_providers
  { archive } }` block (A8) → `Duplicate required providers configuration` because `provider.tf` owns that
  block and the agent is told not to touch it (A9) → removed it (A11) → `provider registry.terraform.io/
  hashicorp/archive was not found in any of the search locations` (A12) → inspected the mirror (A14) → gave up
  on the provider (A16) → hand-built zips (A19) → rewrote to `filebase64sha256` (A21). Fourteen turns and
  roughly 1.5–2k output tokens of pure equipping friction. The awscdk image *does* ship `zip` (its
  Dockerfile line 60) and the terraconstructs mirror *does* ship `archive` 2.8.0 (added in fix-round-3
  precisely because that arm's own inline-code path needs it). CLAUDE.md forbids coaching around "if your
  toolchain requires a code archive"; it does not require handicapping the toolchain. The `archive` provider
  is the standard way to package inline Lambda code in HCL; withholding it (while giving tcons its
  equivalent) is an equipping asymmetry against hcl-raw.
- **The agent cannot add a provider at all** ("Do not create, modify, or delete `provider.tf`"), while the
  L2 arms add providers as npm dependencies. On a scenario needing `archive`, `random`, `null`, `time`, or
  `tls`, hcl-raw is structurally blocked. This is not the arm's property; it is the workspace split's.
- **Skeleton header survives into the deliverable.** `# Generated skeleton -- generator/gen.py … Do not
  hand-edit this header; regenerate instead (`make gen`)` and `# TODO(agent): see the task instruction for
  what to create here.` remain at the top of AbZbQXi's, AiV6ppW's and fvL6ddy's final `main.tf` (and were
  copied verbatim into `/logs/agent/agent-output.txt` by AbZbQXi A9). Harmless to grading; a reviewer would
  reject the file. It also names `generator/gen.py` and `make gen`, i.e. the harness.
- **tier-1 FAIL is silent** — see §6.6. An hcl agent that re-read the verifier could not learn why it failed
  (the agent never sees the verifier, but the operator reading `test-stdout.txt` cannot either).

### 2.3 terraconstructs

For the agent: the baked `tsc` compile and `cdktf.json`'s chained `tsc && node main.js` worked every time;
`main.ts` carries the region; `terraform` and `cdktn` are both on PATH and both deploy paths were used
(`cd cdktf.out/stacks/… && terraform apply` in 8tyeqwP/YudrrS4, `npx cdktn deploy` in SSXBd6K/saaxzSo).
The `archive` provider was in the mirror, so `Code.fromInline` deployed on the first init (8tyeqwP A47).

Against the agent:

- **All vocabulary must be mined from `.d.ts` files; there is no README content for the AWS constructs.**
  YudrrS4 A35–A36 looked for a README/examples and found `node_modules/terraconstructs/README.md` has zero
  hits for `RestApi|LambdaIntegration|apigateway|Lambda`. The result is 13–28 `node_modules` reads per step
  (table §0) and first-write turns of A22/A48 on apigw step 1 vs A14/A5 for awscdk.
- **Names diverge from aws-cdk-lib in ways the agent's prior predicts wrongly, reproducibly.**
  `compute.Function` does not exist (it is `LambdaFunction`): tsc error at 8tyeqwP A24 *and* YudrrS4 A50 —
  2/2 apigw trials wrote `compute.Function` first. `ManagedPolicy.fromAwsManagedPolicyName(scope, id, name)`
  needs a scope and id (8tyeqwP A24 "Expected 3 arguments, but got 1"). The `aws` barrel is
  `terraconstructs/lib/aws` with `compute`/`iam` namespaces, and `Size` lives at `terraconstructs/lib/size`
  (oirNgaR A17–A25 spent 9 turns on this; A29–A30 rewrote `aws.compute` → `compute`). These are the
  concrete atoms of the "vocabulary cost" term.
- **Silent L2 defaults that the agent must discover and undo.** `RestApi` creates a CloudWatch role +
  `aws_api_gateway_account` (both apigw trials disabled it, §1.2); `LambdaFunction` creates a
  `DefaultPolicy` inline policy, log groups and *two* `aws_lambda_permission`s per method (one `Test…`)
  — 8tyeqwP deployed 23 resources vs hcl's 15 and awscdk's ~10 CFN resources. None of this is graded, but it
  is all read by the agent at A33/A41 and slows the "is this right?" check.
- **`npx cdktn synth` floods tool results with spinner ANSI.** Each synth returns ~40 lines of
  `⠏ Synthesizing` escape sequences (every tcons trial, e.g. twcAkP7 A17, YudrrS4 A50/A56); `cdktn deploy`
  output is buffered so the background task file stays empty until completion (SSXBd6K A21–A24, saaxzSo
  A15–A17 "Bash completed with no output"). Cache tokens and confusion, not output tokens.
- **`/usr/local/bin/preflight.sh` is baked into the image** and says "this is the tier the arm is actually
  graded on (docs/iac-abstraction-aws-bench-plan.md Phase 2 …)". No agent opened it, but it is readable
  prompt surface with grading vocabulary.
- **No `ps`/`strings`** in the image (saaxzSo A25 `ps: command not found`, A68 `strings: command not found`;
  bmocEVR A37 on hcl-raw). The agents scanned `/proc` instead (bmocEVR A38). Baseline-utility gap on both
  TF images; awscdk ships `procps`? (not verified — no awscdk trial needed it).

### 2.4 Harness cost still charged to the agent, pre-32 vs post-32

| cell | pre-32 (tokens / turns) | post-32 attempt 1 | post-32 attempt 2 |
|---|---|---|---|
| ecs hcl | 1,152 / 8 (GHVHuVa) | 1,244 / 9 | 1,158 / 10 |
| ecs tcons | 4,641 / 39 (iWQciUF) | 6,099 / 44 | 3,947 / 25 |
| apigw awscdk (cum.) | 8,460 (9VyERV5) | 8,447 | 10,314 |
| apigw hcl (cum.) | 13,565 (qSyGeRD, 2× `UnrecognizedClientException` per step) | 13,480 | 13,781 |
| nrr awscdk | 2,727 (9jQ22cG) | 2,514 | 3,103 |
| nrr hcl | 5,382 (52MJyK2) | 4,502 | 10,487 |
| nrr tcons | 11,558 (KJM6cJY) | 11,024 | 10,937 |

**The Amendment-32 tax removal is invisible at the token level at n=2.** apigw hcl 13.6k → 13.5k/13.8k; nrr
tcons 11.6k → 11.0k/10.9k. The pre-32 seam cost the agents a few hundred tokens (one failed apply + one
`export`), well inside within-arm variance (nrr hcl 4.5k vs 10.5k). What Amendment 32 fixed is *validity*
(0 exceptions and 0 voided rows in 18 trials vs 3 `AgentSetupTimeoutError` + 3 `NonZeroAgentExitCodeError`
+ 4 voided rows in the comparison set), not tokens-to-green. Worth stating that way in DECISIONS.md rather
than implying the metric moved.

Harness cost that *is* still charged, per arm, with the evidence: region (§2.1, all arms, 1–2 turns);
`zip`/`archive` (§2.2, hcl only, 2–14 turns); CloudWatch-role default + possibly fictional IAM constraint
(§1.2, tcons only, 4–6 turns); Bash timeout → background → `TaskOutput` loop on hung applies (§1.3, TF
arms, 5–9 turns); malformed tool calls (§6.8, YudrrS4 ×2, 2 turns); bin/app.ts-induced probing (§2.1,
awscdk, ~3 turns).

---

## 3. Arm differences and the §3 law

### 3.1 Where the L2 encoded the right answer for free

Only one place in this battery: **ecs-swappiness on both L2 arms** (4/4). Delivery mechanisms differed
(§1.1): terraconstructs delivered via JSDoc read before writing (2/2), awscdk via synth-time silent drop
caught by artifact inspection (2/2). The awscdk channel is fragile — it requires the agent to look at the
template — and cheap (the fix took 4–5 turns after the first synth); the tcons channel is robust but was
bundled with 10–25 turns of vocabulary reading that awscdk did not need (awscdk's agents "knew"
`ecs.LinuxParameters`, `Ec2TaskDefinition`, `ContainerImage.fromRegistry` without reading anything).

### 3.2 Where the model already knew, and the abstraction was only vocabulary (+ compression)

**apigw-redeploy.** The model wrote `triggers`/`depends_on`/`create_before_destroy` unprompted in HCL (2/2)
and extended the hash in step 2 (2/2). By the §3 law's own logic (closed-book "knows" → abstraction
should *lose*), tcons losing (16–19k) is predicted; awscdk *winning* (8.4–10.3k vs hcl 13.5–13.8k) is not.
The residual is **compression**: the awscdk solution is ~45 lines (fkvo6HF A14), the HCL one ~200 lines /
15 resources (AiV6ppW A8), and output tokens scale with what has to be typed. The law as written —
`advantage ≈ encoded experience − vocabulary cost` — has no term for this, and on a scenario where the
first term is zero the whole awscdk margin is that missing term. Proposed refinement (§5 P3): 
`advantage ≈ encoded experience + compression − vocabulary cost − default-side-effect discovery`, where the
last term is the cost of finding and undoing what the L2 adds unasked (CloudWatch role, task role, test
permissions, log groups — §2.3).

### 3.3 Where the abstraction misled or obstructed

- **terraconstructs on named-resource-replacement**: the L2 hides `lifecycle`; both agents needed ~15
  turns to break out (§1.3). This is a *negative* encoded-experience term — the L2 encodes nothing about
  replacement ordering *and* removes the knob.
- **terraconstructs naming vs the CDK prior**: `compute.Function` (2/2 wrong), `fromAwsManagedPolicyName`
  arity, import barrels (§2.3). The agent's aws-cdk-lib prior is the source of the error; the closer the
  arm gets to aws-cdk-lib's names, the lower this term.
- **awscdk's `CfnOutput`** is not an escape hatch (§6.4); no awscdk trial left the L2 anywhere in this
  battery.
- **hcl-raw's transparency on ecs**: the plan echo (`swappiness = 42`) is reassurance for the wrong
  answer (§1.1). On apigw and NRR the same transparency helped: the plan's `-/+` vs `+/-` glyph is the
  entire diagnosis of the NRR trap, and hXhAAe4 read it (A10); bmocEVR and SSXBd6K saw it and ignored it.

### 3.4 What works with / against the model's intuition, per arm

**awscdk** — with: construct names and idioms are in the model's head (no `.d.ts` reads on apigw step 1 in
either trial; first write at A5 in jDwLKPF); `cdk diff` before deploy (Ttym8Ju A9) is a native habit;
`Code.fromInline` avoids the packaging problem entirely. Against: region/bootstrap uncertainty prompts
probing (§2.1); the synth output is noisy; the agent tends to read `bin/app.ts` and pick up harness
vocabulary.

**terraconstructs** — with: once the names are right, the code is the same shape as awscdk and the agent
reasons about it the same way; `cdktn diff` exists and was used (SSXBd6K A11). Against: everything in §2.3;
plus the agent's "verify the synthesized JSON with python" loop (8tyeqwP A33–A43, YudrrS4 A59–A66) is
longer because the JSON has more resources and the agent doesn't know which are expected.

**hcl-raw** — with: no vocabulary cost at all (first write A4–A8 everywhere; zero node_modules reads);
plan glyphs are the diagnosis; state is a file the agent can `cat` (bmocEVR A26). Against: packaging
(`zip`/`archive`, §2.2); the frozen `provider.tf`; the plan's echo of unvalidated JSON blobs (ecs); every
fix is more lines.

### 3.5 Within-arm variance and what drove it (n=2, so descriptive only)

- ecs tcons 25 vs 44 turns / 3.9k vs 6.1k: oirNgaR's A17–A26 import-surface exploration + a stricter
  self-check policy (A31–A32 confirmed `containerName` exists, A40 looked for artifacts to clean up).
  Same knowledge, different thoroughness.
- nrr hcl 17 vs 56 / 4.5k vs 10.5k: prior knowledge (hXhAAe4) vs learn-by-hang (bmocEVR). This is the
  largest ratio in the battery (2.3×) and is a coin flip on one fact; the closed-book probe (M6) would
  predict it.
- apigw tcons s1 62 vs 81 / 9.2k vs 12.6k: reading depth before first write (A22 vs A48). YudrrS4 also lost
  2 turns to malformed tool calls (§6.8) and A63's "Wasted call — file unchanged" re-read.
- apigw awscdk s2 28 vs 38 / 4.4k vs 6.0k: entirely the 403-blip investigation depth (fkvo6HF polled;
  jDwLKPF ran `test-invoke-method`, `get-rest-api`, cache-bust, 5× loop).
- awscdk NRR and both hcl ecs attempts are within 20% — the low-variance cells are the ones where the
  agent had nothing to discover.

---

## 4. Per-arm pros / cons / suggested improvements (ranked; "coaching" flags CLAUDE.md conflicts)

### 4.1 awscdk

Pros: lowest tokens on every scenario; zero vocabulary reads on apigw; the only arm where the NRR trap is
structurally absent; self-verification of the synthesized template caught the ecs trap 2/2.
Cons: hidden equipping via `cdk.json` flags (§2.1); bootstrap/region probing; harness-vocabulary leak in
`bin/app.ts`; `CfnOutput` false-positive in the escape-hatch metric.

1. **Strip the `bin/app.ts` comment to what the file is** (evidence: fkvo6HF A10 `find / -iname deploy.sh`,
   A12 CDKToolkit probe; every awscdk trial read it). Changes: removes ~2–4 probing turns per live trial and
   a grading-vocabulary leak. Not coaching — it removes text.
2. **Stage `AWS_REGION=us-east-1` in the agent env on all arms** (evidence: 6 NoRegion/export events across
   arms). Changes: −1–2 turns per trial that verifies with the CLI; symmetric. Not coaching (environment
   fact, same as `AWS_PROFILE`).
3. **Decide whether the `cdk.json` feature-flag context is part of the arm.** Either document it as
   equipping (and give tcons an equivalent `cdktf.json`/context — there is none for CloudWatch role) or
   generate a minimal `cdk.json` without the 39 flags and measure the difference (§5 P6). Changes what
   "awscdk L2" means in the comparison.
4. **Fix `metrics/extract_signals.py` ESCAPE regex** to exclude `CfnOutput`/`CfnParameter`/`CfnCondition`
   (§6.4). Changes: escape-hatch incidence for awscdk apigw goes from "YES both steps" to "no".
5. (Coaching — not allowed) telling the agent the region or that CDKToolkit is bootstrapped in the prompt.

### 4.2 hcl-raw

Pros: no vocabulary cost; plan glyphs make replacement ordering visible; cleanest bootstrap; the only
arm whose transcripts contain the whole solution as plain text a reviewer can read in one screen.
Cons: packaging friction; frozen provider block; fails ecs "cheap"; the plan echo reassures wrong answers.

1. **Add `hashicorp/archive` to `arms/hcl-raw/environment/mirror-src/main.tf` and `zip` to the image
   baseline** (evidence: AiV6ppW A4, fvL6ddy A8–A21 = 14 turns; tcons mirror already has `archive`;
   awscdk image already has `zip`). Changes: removes a ~1.5–2k-token asymmetric tax on any Lambda scenario.
   Not coaching — equipping parity. Note the `terraform { required_providers }` block would still be
   frozen in `provider.tf`; either pre-declare `archive` there or allow a second `required_providers` via a
   separate agent-owned `versions.tf`. The latter is cleaner: it lets the hcl agent add providers the way
   the TS agents add npm packages.
2. **Print the tier-1 deny reasons in `static_tiers.sh`** (§6.6). Changes nothing for the agent; makes the
   operator's post-mortem possible.
3. **Stop emitting `TODO(agent)` and the `make gen` regeneration note into the skeleton `main.tf`** (kept in
   3/4 hcl deliverables). Changes: nothing measurable; removes harness naming from the entry file.
4. (Coaching — not allowed) any hint about `maxSwap`, `triggers`, or `create_before_destroy`; any "you may
   need to package the code" sentence.

### 4.3 terraconstructs

Pros: JSDoc delivered the ecs trap 2/2 before the first write; `cdktn diff` available; deploy via either
CLI works; the L2 shape lets the agent reason like awscdk once the names are known.
Cons: highest tokens everywhere; name divergence from aws-cdk-lib; silent defaults (CloudWatch role, test
permissions) that the agent must find and undo; hidden `lifecycle`; spinner noise; no construct docs beyond
`.d.ts`.

1. **Library-side (not harness): align names with aws-cdk-lib where cheap** — `Function` alias for
   `LambdaFunction`, `fromAwsManagedPolicyName(name)` overload, default `cloudWatchRole: false` (or honour a
   context flag as aws-cdk-lib does). Evidence: 2/2 apigw trials wrote `compute.Function` (8tyeqwP A24,
   YudrrS4 A50); 2/2 found and disabled the CloudWatch role. Changes: predicted −10–20% turns on apigw step
   1 (§5 P4). This is the maintainer's own library, so it is legitimate to test as a *version* factor, and
   it must be pre-registered as such (disclosure already in README).
2. **Expose `lifecycle` on the L2s that wrap replaceable resources** (SecurityGroup at minimum). Evidence:
   ~15 turns of escape-hatch discovery in 2/2 NRR trials + KJM6cJY. Changes: NRR tcons cost would likely
   converge toward hcl's; escape-hatch incidence would drop from 3/3. Same caveat as above — a library
   change is a new arm version, a new cell.
3. **Suppress the spinner** (`CI=1`/`--no-color`/`TERM=dumb` in the image env) so `cdktn synth`/`deploy`
   emit plain lines. Evidence: every tcons transcript. Changes: cache tokens and one less "output is empty"
   confusion (SSXBd6K A21–A24); not coaching.
4. **Remove `preflight.sh` from the runtime image** (or strip its grading sentence). Evidence: readable
   prompt surface; unread in this battery. Changes: none measurable.
5. **Add `procps` to both TF images** (bmocEVR A37, saaxzSo A25). Trivial.
6. (Coaching — not allowed) naming `compute.LambdaFunction`/`MockIntegration` in the prompt — *unless* the
   awscdk line keeps its parenthetical, in which case parity demands the same on tcons. The non-coaching
   fix is to drop awscdk's parenthetical (§1.2 item 1).

### 4.4 Cross-arm

1. **Verify or delete the IAM-path constraint** (§1.2 item 2). If unenforced, its only effect was to make
   tcons agents undo the CloudWatch role; that is a fictional cost.
2. **Add a "blast radius / plan glyph" column** (M1): `-/+` vs `+/-` observed before first apply, and
   whether the agent applied anyway (bmocEVR yes, SSXBd6K yes, hXhAAe4 no). This is the most informative
   single bit in the NRR trajectories and it is deterministic to extract.
3. **Consider disabling Claude Code auto-memory in trials** (§6.7). It is equipping that only some agents use.

---

## 5. Hypotheses worth pre-registering

Each is falsifiable, names the experiment, and maps to a roadmap item.

**P1 — Closed-book probe predicts hcl-raw's reward per trap (M6).** Prediction from this battery: Sonnet-5
answers "does memorySwappiness take effect without maxSwap?" *wrongly* (evidence: 0/2 hcl and 0/2 awscdk
first writes included maxSwap), answers "how do you force API Gateway to redeploy on route changes in
Terraform?" *correctly* (2/2), and answers "what happens when you rename an in-use aws_security_group?"
correctly ~50% (1/2 hcl, 0/2 tcons acted on it, 1/1 pre-32 tcons). Experiment: M6 probe, 10 samples per
question, then predict the hcl-raw green rate for all 17 specs before running them. Falsified if a trap
the probe "knows" fails hcl-raw ≥ 50% or vice versa.

**P2 — The awscdk ecs advantage is conditional on artifact inspection.** Prediction: among awscdk
ecs-swappiness trials, those whose transcript contains no read of the synthesized template score 0.0.
Experiment: ecs-swappiness awscdk k=10 (read-only, ~$0.20 each); classify trajectories by "inspected
template before finishing". Falsified if any non-inspecting trial scores 1.0 (which would mean the model
knew maxSwap a priori that time). Maps to M1 (a new deterministic column: "inspected own artifact") and M5.

**P3 — On traps the model already knows, tokens-to-green is explained by solution size, not by arm.**
Prediction: regress output tokens on bytes of the final entry file across (scenario, arm, attempt); the
awscdk–hcl residual on apigw-redeploy is ≈ 0, while on ecs-swappiness it is large and negative for hcl.
Experiment: no new trials — 18 rows exist; add the 2026-08-20 rows. Maps to the §3 law refinement
(compression term) and M6. Falsified if apigw's residual is as large as ecs's.

**P4 — terraconstructs' vocabulary cost is concentrated in a handful of aws-cdk-lib name divergences.**
Prediction: a terraconstructs release adding `Function` as an alias, a single-argument
`fromAwsManagedPolicyName`, and `cloudWatchRole: false` default cuts apigw step-1 turns by ≥ 30% and
tokens by ≥ 20%, with no change on hcl/awscdk. Experiment: apigw-redeploy tcons k=4 on the current version
vs k=4 on the patched version (new equipping hash, new cell). Maps to M2 (equipping factorial — here the
"equipping" is the library version). Falsified if the drop is < 10%.

**P5 — On the TF arms, an NRR trial that applies before adding `create_before_destroy` always spends
> 600 s wall-clock and > 2× the tokens of one that does not.** Prediction: tcons 100% of first-attempt
deploys hang (the L2 hides the knob, so nothing in the code prompts the thought), hcl ~50%. Experiment:
NRR k=6 per TF arm; record "plan glyph seen before first apply" and "applied anyway". Maps to M1 (blast
radius) and M4. Falsified if a tcons agent adds the override before its first deploy at a rate > 30%.

**P6 — awscdk's `cdk.json` feature flags are worth measurable tokens on apigw.** Prediction: awscdk
apigw-redeploy with `@aws-cdk/aws-apigateway:disableCloudWatchRole` removed costs +3–6 turns in step 1
(the agent discovers the extra role, as tcons did) and, if the IAM-path constraint is real, some 0.0s.
Experiment: k=4 with/without the flag (equipping factor, new hash). Maps to M2. Falsified if no trial
mentions the CloudWatch role.

**P7 — Staging `AWS_REGION` removes 1–2 turns per live trial on every arm and changes tokens by < 5%.**
Experiment: k=4 per arm on NRR with/without. Maps to M7 (harness throughput/hygiene). This is a
pre-registered *null* prediction on the headline metric — worth having on record so the change cannot be
accused of moving the numbers.

**P8 — Giving hcl-raw `archive` + `zip` removes ≥ 1k output tokens from apigw step 1 and does not change
step 2.** Experiment: apigw hcl k=4 after the mirror/image change. Maps to M2/M7. Falsified if step-1
tokens stay ≥ 6.5k.

**P9 — The Amendment-32 seam removal did not move tokens-to-green (null).** Prediction: pooled pre-32 vs
post-32 within-arm token difference on apigw hcl and nrr tcons is inside the within-arm attempt spread.
Experiment: none needed beyond what exists (§2.4 table), but state it in DECISIONS.md so the amendment's
claim is "validity", not "cost".

**P10 — Edge-propagation on apigw step 2 costs every arm the same.** Prediction: the 403-blip turns
(from first 403 to first 200) are 8–16 on every arm and do not correlate with arm. Experiment: extract
from existing 6 step-2 transcripts + future runs; if confirmed, either switch the API to
`endpointConfiguration: REGIONAL` in the *reference* solutions only (does not touch prompts) — no, that
would not change agent behaviour — or simply accept it as arm-neutral noise and document it. Maps to M1
(a "waited for propagation" column). Falsified if one arm systematically escapes it.

---

## 6. Harness / oracle findings

**6.1 Live temporary credentials were captured into a stored transcript.** fkvo6HF step 1 A8 ran
`env | grep -i aws; cat ~/.aws/config; cat ~/.aws/credentials | head -5`; the tool_result — access key id,
secret, and session token for the `PRIMARY` profile — is now in
`jobs/amend32-promotion/2026-08-27__21-50-09/apigw-redeploy-awscdk__fkvo6HF/steps/01-initial-deploy/agent/
claude-code.txt` and in the session `.jsonl`. They are STS temporaries (expired), but CLAUDE.md's "Never
write AWS credentials to a file" is violated by the harness on the agent's behalf. jDwLKPF A14 did the
same read but piped through `sed 's/=.*/=[REDACTED]/'`. Fix: redact `aws_secret_access_key=…`,
`aws_session_token=…`, `ASIA[A-Z0-9]{16}` at transcript ingest (`gates/` or the Claude Code agent wrapper),
and add a gate that fails a job whose transcripts contain them. Also consider whether `~/.aws/credentials`
needs to be world-readable to the agent's shell at all (an SDK-only credential process would not be).

**6.2 `AWS_REGION` unset in the agent environment** (§2.1). Six region errors/exports across four arms.
Stage it with the profile.

**6.3 hcl-raw image/mirror lacks `zip` and `hashicorp/archive`** while the other arms have their
equivalents (§2.2). Equipping asymmetry with a 14-turn worst case.

**6.4 `metrics/extract_signals.py` awscdk escape-hatch regex is `\bCfn[A-Z]\w+` and matches
`cdk.CfnOutput`.** Both awscdk apigw trials use `new cdk.CfnOutput(this, "ApiUrl", …)` and nothing else
from L1; the grep for `Cfn[A-Z]\w+\(|addOverride|defaultChild|…` lights up only on `CfnOutput` in those
files. ROADMAP §3 finding 5 ("CDK required an escape hatch on `apigw-redeploy`, both steps — first
mechanical escape-hatch evidence") is a false positive of this regex and should be retracted. Fix: exclude
`CfnOutput|CfnParameter|CfnCondition|CfnMapping|CfnResource\b`-free names, or require
`new\s+\w*\.?Cfn(?!Output|Parameter|Condition|Mapping|Rule)`.

**6.5 `docs/live-results.md` NRR paragraph: "with the tier fixed, the escape hatch disappeared" is
wrong.** KJM6cJY's final `scenario-stack.ts` contains `(ssmEndpointSg.node.defaultChild as
TerraformResource).lifecycle = { createBeforeDestroy: true }`; both battery tcons trials use the same class
of override; the spec itself says the fix on this arm *requires* it. Escape-hatch incidence for tcons on
NRR is 3/3 and structural. The sentence should say the opposite: the escape hatch is the arm's only route.

**6.6 tier-1 FAIL prints no reason.** `ecs-swappiness-hcl-raw__8grne9A/verifier/test-stdout.txt` shows
`== tier-1: OPA/Rego ==` then blank, then `tier1_status=FAIL`. `opa eval`'s deny set should be echoed (it
is the only explanation of a 0.0 an operator gets).

**6.7 Claude Code auto-memory is enabled inside trials.** Init event:
`"memory_paths":{"auto":"/logs/agent/sessions/projects/-app-project/memory/"}`. bmocEVR A52–A55 checked the
directory ("Empty memory directory — I'll save the non-obvious Terraform gotcha") and wrote
`feedback_sg_rename_create_before_destroy.md` + `MEMORY.md` — a complete answer key for the NRR trap.
Per-trial mounts kept it isolated here (no other trial's init or transcript references a memory file), but:
(a) it is agent equipping that fires stochastically (1/18), (b) on multi-step tasks the path is identical in
step 1 and step 2 (`/logs/agent/sessions/...`) and isolation depends on Harbor remounting `/logs/agent` per
step — if that ever changes, step-1 memory becomes a third foreshadowing surface, and (c) the file is a
prompt-rule violation if it were ever read. Recommend disabling auto-memory in the agent config for trials
(and asserting in the trajectory audit that no `memory/` write occurred, or that none was read at init).

**6.8 Malformed tool calls charged as turns.** YudrrS4 step 1 A18 and A23:
`<tool_use_error>InputValidationError: … An unexpected parameter `descriptio` was provided`. The model
emitted a truncated `description` key on a `Bash` call; the harness rejected it; two turns and two
`is_error` results. Rare (2/24 transcripts) but it is neither arm nor scenario; the trajectory audit could
flag `InputValidationError` counts so they can be netted out of turn counts.

**6.9 Bash tool timeout drives the TF-arm turn counts on NRR.** Default 120 s (300 s once) → "moved to the
background" → `ToolSearch select:TaskOutput` → `TaskOutput block:true timeout:180000/300000` ×3–4 →
`TaskStop` (bmocEVR A10–A22, saaxzSo A13–A27, SSXBd6K A13–A25). A provider that retries
`DependencyViolation` for 10–15 minutes turns one hung apply into 6–9 turns and ~15 min of wall-clock.
Turns are not the headline metric, but `num_turns` is reported and compared; note that on NRR, tcons's
59/75 vs awscdk's 16/18 is roughly half waiting. Consider raising the Bash timeout for mutating tasks (the
trial budget is 3,600 s) so an apply completes or fails in one call — this is harness configuration, not
coaching. Also: `TaskStop` did not actually kill the terraform process (bmocEVR A38 shows PIDs 411/427 still
alive; `force-unlock` reported "LocalState not locked" while `plan` reported the lock held, A28/A33/A35) —
a Claude Code background-task defect the agent had to work around with `/proc` + `kill` (A38–A40).

**6.10 Two "turn" definitions are in play.** `docs/live-results.md` and `corpus-status.html` report
assistant-message counts (ecs hcl 9/10 — matches my A-numbering); Claude Code's own `result.num_turns` is
6 for the same trials (it counts API round-trips differently). `result.json` step_results carry no
`started_at`/`finished_at`, so per-step wall-clock has to come from the stream `duration_ms`. Pick one and
name it in the schema.

**6.11 Thinking is not captured.** Every `thinking` block in the stream is empty although
`output_tokens_details.thinking_tokens` is non-zero (up to 5,261 in bmocEVR). Read-before-write and
"moment of understanding" analyses can only use tool calls and visible text. If the SDK option to include
thinking summaries is available, enabling it would make the trajectory audit sharper; if not, note that
rbw% counts thinking tokens it cannot see.

**6.12 saaxzSo token recovery (known).** `result.json` `n_output_tokens: None`; `trial.log` line 35
`steps[17].step_id: expected 18 … got 19`; the `claude-code-stream` fallback gives 11,024/$0.656. Confirmed
the stream's terminal `result` event is intact. The gap is likely the malformed-tool-call class (§6.8) or
`TaskOutput` events — worth checking harbor's converter against a `TaskStop`/`TaskOutput` step sequence.

**6.13 Reset dominates wall-clock.** 12 mutating trials: agent phases sum to ~1h05m, `scenario-reset`
phases 7m37s–13m18s each (`scenario-reset/result.json` started/finished), ~1h55m total — half the 3h54m.
Every reset ran strictly serially. M7's second scenario (or a per-task reset) is the throughput lever.

**6.14 apigw live_check is robust to the propagation blip; NRR's is 120 s.** `POLL_TIMEOUT_S = 180` /
`POLL_INTERVAL_S = 5` on apigw, samples show `t: 0.4–1.0` because the agents had already waited; the
regression check polls the full 30 s window. NRR's `POLL_TIMEOUT_S = 120` with `polled_for_s: null` on all
six. Fine for these scenarios; note the apigw window must exceed the longest blip observed (~100 s in
fkvo6HF) — it does, but not by a wide margin.

**6.15 Residual prompt-surface leaks under `environment/`** (none names a trap): awscdk `bin/app.ts`
comment ("synth-only oracle tiers", "deploy.sh's `cdk bootstrap`", "mutation agent", "Amendment 24",
"arm parity", "hcl-raw arm"); hcl `provider.tf` header ("cdktn-bench hcl-raw arm … generated task's
workspace"); all skeleton headers ("Generated skeleton -- generator/gen.py … `make gen`",
"TODO(agent)"); tcons `/usr/local/bin/preflight.sh` ("the tier the arm is actually graded on"); the apigw
shared instruction naming the other arms. `test_workspace_seed.py::TestBrownfieldPromptSurface` scans for
trap words; a second scan for harness words (`oracle|tier|grade|verifier|amendment|arm parity|
generator/gen.py`) over every byte the Dockerfile COPYs would have caught all of these.

**6.16 Instruction parity gap** (§1.2 item 1): awscdk's `language_line` names constructs; tcons's does
not. `generator/check_parity.py` diffs only the shared prefix, so this passes by design; it should not.

**6.17 Amendment 32's promotion claim checks out.** Zero `InvalidClientTokenId|UnrecognizedClientException|
mock-|cdktn_bench_live|CDKTN_BENCH_LIVE` strings in any of the 24 agent transcripts; no
`aws-unavailable` marker; `aws sts get-caller-identity` returned the bench role on the first call in every
trial that ran it (fkvo6HF A6, jDwLKPF A9, AiV6ppW A4, fvL6ddy A4, YudrrS4 A68, 8tyeqwP A45).
