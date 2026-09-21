# A fourth arm: Terraform composed from registry modules

Status: planning note, 2026-09-21. Not scheduled. Three companion surveys
carry the evidence: `plan-normaliser-survey.md` (plan JSON shapes and prior
art), `sast-module-handling.md` (how Checkov, Trivy, TFLint and the plan
readers treat modules), `tf-module-registry-loopback.md` (the offline module
registry, executed against terraform 1.15.8).

Owner decisions taken while planning: `hcl_modules` is an ARM, gated per spec
exactly like terraconstructs (`arms.hcl_modules { enabled, reason }`), never a
scenario treatment attribute; that closes ROADMAP open decision 4. Module
delivery is one central vendored set served by a compose sidecar, never
per-spec local paths. Nested stacks on awscdk are refused, not normalised.

## Where the repo stands

* The pre-registration named "TF modules (`terraform-aws-modules`)" as its
  own authoring arm with its own equipping row (Terraform MCP plus Babenko
  authoring skills) and framed it as the rebuttal to "raw HCL is a strawman".
* Amendment 2 dropped it from the v1 build, by owner direction.
* ROADMAP M3 reopens it as a falsification test ("the most obvious
  practitioner objection to our headline stands unanswered"), predicts
  modules win on composition traps and lose on property-semantics traps, and
  asks for decoy modules so selection cost is measured. Open decision 4: a
  fourth arm on every scenario, or a treatment on a subset.
* Nothing in the grading stack understands modules. `tf_jsonpath` reads
  `planned_values.root_module.resources` only; every Rego policy reads the
  root module directly; `hcl_traversal.rego` refuses `module.x.out` and
  `var.*` by name; the one module-aware rule in the corpus exists to DENY
  module usage because a resource inside a module block is otherwise
  ungraded and indistinguishable from a correct one.

## 1. Do the oracle tiers survive modules?

Not as written, and the survey corrected one assumption: **`planned_values`
cannot express unknown.** An unknown attribute is absent from `values`, so a
hoist over `child_modules` alone leaves the three-valued grader blind to
unknowns. The unknown flag exists only in
`resource_changes[].change.after_unknown`; `resource_changes[]` is already
flat, carries `module_address` and instance-keyed addresses, and its
`change.after` was byte-identical to the hoisted `planned_values` values in
every fixture. The normaliser therefore hoists both sides and carries
`after_unknown` across (gaps to handle: plan-time data sources live in
`prior_state`, deletes are `after: null`, no `sensitive_values`, deposed
objects break address uniqueness). This is the same read blast radius (M1)
needs, so the artifact is captured once.

The configuration side is the real work, not the recursion: child expressions
are module-local and unexpanded (one `module_calls.many` backs `module.many[0]`
and `[1]`), `dynamic` blocks are absent from the configuration representation,
and `for_each = toset([...])` on a module call emits no `for_each_expression`
at all. `terraform graph -type=plan` carries resolved cross-boundary edges,
DOT only, node level: a cross-check, not an input. No library exposes a
reusable cross-module resolver (terraform-json is types; Checkov's plan path
discards `var.`/`local.` references; Trivy's plan scanner never reads
`after_unknown`); Regula (archived) and terraform-compliance hold the algorithm
but mount resolved references into value slots, destroying the
held/contradicted/unresolvable distinction, and Regula misses every indexed
module. Port their shapes into the Python tier-0 driver; a 70-line prototype
already resolves two-level `var` chains and root output chains. Honest
unresolvable list: module `count`/`for_each`, indexed module outputs, `toset`
for_each, `dynamic` blocks, multi-reference outputs, unpassed inputs falling
back to module defaults. Effort about three days.

The SAST tools confirm the failure to avoid: Checkov, Trivy and TFLint all
SKIP a module whose bytes are not present and emit no finding, and TFLint
drops an in-module issue entirely when the flagged expression has no direct
`var.` reference (module defaults and internal locals produce nothing). That
is "unresolvable reported as held", the exact defect the three-valued
contract exists to prevent. One idea worth keeping from Trivy: a plan
snapshot (`terraform plan -out`) embeds every module's source, so a full HCL
evaluation is possible offline from the artifact alone.

### Nested stacks on awscdk

Same blind spot: a `NestedStack` synthesizes to a separate template with an
`AWS::CloudFormation::Stack` in the parent, invisible to every tier-0 path
and cfn policy over `ScenarioStack.template.json`. Decision: a
generator-emitted awscdk tier-1 rule denies an unprompted
`AWS::CloudFormation::Stack` with a message naming why (the oracle reads the
root template only), mirroring the module-usage deny in
`s3-notification-authoritative-singleton`. No ticket asks for nested stacks.

### The plan shapes, tier by tier

`terraform show -json` places module resources under
`planned_values.root_module.child_modules[].resources[]` (recursively) with
addresses `module.<call>.<type>.<name>`, and the configuration side under
`configuration.root_module.module_calls.<call>.module.resources[]`, whose
`expressions.<attr>.references` name `var.<input>` inside the module; the
root-side value arrives through `module_calls.<call>.expressions.<input>`.
Two invocations of one module are two `child_modules` entries with different
addresses.

What that breaks, tier by tier:

| tier | today | under modules |
|---|---|---|
| 0 (jq over plan) | `$.planned_values.root_module.resources[?(@.type=='X')]` | resolves to nothing: no node, so `exists` contradicts and every value assert reads the empty set |
| 1 (Rego, plan) | `input.planned_values.root_module.resources` | same blindness; graph-edge rules over `configuration…references` see `var.bucket_name`, never the root resource |
| 1 (hcl_traversal) | resolves `local.*` in the root module's own files | refuses module boundaries and inputs by design |
| live, idempotence, teardown | read the account or run terraform | unchanged |

The fix is the normaliser described above, not 301 rewritten paths: a pure
function over the plan JSON, hoisting from `resource_changes` and
`planned_values` with `after_unknown` carried, and rewriting configuration
references across the boundary where they resolve (`var.x` inside `module.a`
becomes whatever `module_calls.a.expressions.x` references). Every TF-shaped
arm grades the normalised document, so a module-free plan must normalise to
itself byte-for-byte (a parity gate over all existing hcl_raw and
terraconstructs fixtures, zero drift), and the same asserts then hold on a
module-shaped plan. It lives in the Python tier-0 driver (a `normalize_plan`
step in `ops.py` before jq runs, the same document handed to `opa`), which is
why this arm sequences after the Python verifier work.

Two semantics questions the normaliser cannot answer alone and the spec
must: `eq` demands exactly one node, so an assert written for one bucket
contradicts when a module instantiates two; and a module that hides the
trapped attribute behind a default (or does not expose it) changes the
catch's tier or removes the catch on this arm. `predicted_tier_caught`
therefore needs an `hcl_modules_override` column and `applies_to` decisions
per catch, as terraconstructs already has.

## 2. How do modules reach the agent?

Today only providers are pre-warmed: `terraform providers mirror` at image
build from `mirror-src/main.tf`, a `filesystem_mirror` with no `direct`
fallback, proven offline by preflight under `--network none`. There is no
module mirror, no vendoring, no `.terraform/modules` seeding, and no
mechanism to place a directory tree into the workspace (`seeded_files` and
`workspace_seed.extra_files` are flat per-file COPYs). At trial time the
container has network (live AWS is the only trial mode), so a registry source
would download, but the host gates and preflight need the same bytes offline,
and the equipping hash must pin them.

Decided and executed against terraform 1.15.8 with outbound HTTP blocked
(`tf-module-registry-loopback.md`):

* **The transparent `host` override works over plain HTTP, on loopback, a
  LAN IP and a DNS hostname.** `host "registry.terraform.io" { services = {
  "modules.v1" = "http://<responder>/v1/modules/" } }` in the CLI config
  makes `source = "terraform-aws-modules/s3-bucket/aws"` with a version
  constraint resolve with no TLS, no CA and no discovery request; Terraform
  never consults DNS for a forced host, so `allow_internet` (on across the
  corpus, Harbor's default) is irrelevant to masking. The provider
  `filesystem_mirror` and the `host` block coexist in one file.
* **Responder:** about 90 lines of stdlib Python, three endpoints (discovery,
  `versions` answering only the allowlisted set, `download` answering 204
  with an absolute-path `X-Terraform-Get` to a tarball it serves). Submodule
  sources (`//modules/...`) need nothing extra. A missing module or version is
  a clean `init` error naming the newest available version, never a silent
  upstream fetch. The module protocol has no integrity layer (the lock file
  holds no module entries; `modules.json` records key, source, version, dir
  and is a usable grading artifact for which modules were chosen).
* **Shape: a compose sidecar, per trial.** Harbor merges a task's
  `environment/docker-compose.yaml` extra services after its base file and
  runs one compose project per trial (`up` in `start`, `down` in `stop`), and
  the verifier executes in the same environment. The responder runs as a
  `tf-registry` service, nothing enters the workspace, the agent starts
  nothing, and the same service answers the verifier's `terraform init`. The
  host gates start the same Python file as a subprocess, the way
  `gates/aws_stub.py::running_stub` does.
* **Vendoring:** GitHub tag tarballs for the chosen repositories, pinned by
  commit sha plus a per-file manifest (tarball bytes differ between tag and
  commit archives); about 4 MB pruned; Apache-2.0 throughout. Provider
  coupling: every current version accepts hashicorp/aws 6.58.0 except `eks`
  21.25.1 (needs 6.59), so eks as a decoy means a mirror bump or an older pin;
  eks and lambda pull tls, time, cloudinit, null, external and local into the
  provider mirror. Transitive registry dependency: `kms` exactly 4.0.0 via eks
  and route53, so kms is served at two versions.
* **The Terraform MCP server cannot be the tuned equipping for this arm as
  is:** v1.3.0 hard-codes the public registry URL for module search and
  details with no override. Either a bench-owned index tool replaces it in
  the M2 row, or that row's meaning changes and is re-registered.

Rejected alternative:

* **Vendored local sources.** Same vendored tree, and the agent writes
  `source = "/opt/terraform-modules/s3-bucket"`. Simplest, fully offline,
  but the authoring shape diverges from practice and version selection
  disappears as a measured skill.

Discovery: the responder also serves a search endpoint generated from the
same manifest, decoys unmarked in it, so no per-workspace index file is
needed and the deny-list sweep runs once over the central manifest (anything
the agent can read is agent-visible bytes; a module named after a trap would
leak). The arm's language line states the toolchain fact: registry modules
come from the real `terraform-aws-modules` source with allowlisted versions
per task, discoverable at the registry endpoint. That is the same kind of
sentence as hcl_raw's "(no modules)", so prompt parity holds. The
training-data risk cuts both ways: a model that knows the source string
writes it without probing (M3's near-zero discovery tax), and the responder
serves exactly that string; a model insisting on an unvendored version gets
a visible init failure.

## 3. What else matters

* **Arm plumbing is a closed enum in five places**: `spec_model.Arm`,
  `gen.ARM_DIRNAME`, `gen.ARM_WORKSPACE_SUBDIR`, `shards.ARM_ORDER`,
  `audit.ARM_TOKEN_PATTERNS` (the terraform patterns copy over), plus
  `arms/hcl-modules/{environment,preflight.sh,README.md}`. Model it like
  terraconstructs: per-spec `enabled` with a reason, so it phases in.
* **Fixtures are the real cost.** Every enabled spec needs a hand-authored
  module-based reference and one broken fixture per catch on this arm,
  proven by falsifiability and grading-proof. Twenty specs is the full bill;
  a pilot of three composition-trap scenarios (bucket hardening, ACM record
  wiring, IAM policy attachment) answers M3's prediction first.
* **Provider pin compatibility.** `terraform-aws-modules` releases carry
  `required_providers` constraints; the vendored versions must accept
  hashicorp/aws 6.58.0 or the mirror bump becomes an amendment.
* **Metrics need no schema change**: a fourth `arm` value in `cell_key`; the
  split is per scenario, so assignments carry over; shards already number
  four. The pre-registration priced three arms, so the factorial and the
  equipping row for this arm are restated in the amendment that reintroduces
  it, which also closes open decision 4.
* **Equipping is the second axis.** The Terraform MCP server and Babenko
  skills are the tuned level for this arm and are measured separately from
  the vendored module set, which is baseline.

## Milestones before the arm exists

1. Python verifier lands (the normaliser lives there).
2. Amendment: arm reintroduced, decision 4 answered, `hcl_modules_override`
   tier column, per-spec enable, factorial and equipping row restated.
3. Plan normaliser with the zero-drift parity gate over every existing
   Terraform fixture, then module-shaped fixtures for the pilot scenarios;
   Rego policies and `hcl_traversal` read the normalised document.
4. Module delivery: vendored set pinned by commit sha in the image, the
   registry responder as a compose sidecar (generator-emitted
   `environment/docker-compose.yaml` for this arm, smoke-drift byte copy
   respected), search endpoint, deny-list sweep over the manifest, preflight
   proving `init` offline against it; the kms dual version and the eks
   provider coupling settled.
5. Arm plumbing and the pilot: three scenarios with references and fixtures,
   falsifiability and grading-proof green, one live promotion trial per arm
   form used.
6. Corpus roll-out, then the tuned equipping level with a bench-owned index
   tool in place of the Terraform MCP server (or the M2 row re-registered).
