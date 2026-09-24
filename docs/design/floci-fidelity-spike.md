# Floci as the trial backend — per-spec fidelity measurement

Measured on 2026-09-24, against the corpus at `ba7b13d` (every fixture staged
from that revision, not from the working tree).

Question: can trials run against the Floci AWS emulator instead of live AWS,
with real AWS kept for spec authoring and acceptance? DECISIONS.md Amendment 32
made live AWS the only trial mode and left "using an emulator in a trial, or as
a live-check substitute" as a separate decision needing a measured false-green
rate. This is that measurement.

## Setup

| what | value |
|---|---|
| image | `floci/floci:latest` |
| digest | `sha256:f5aa8c18302cedb4f2385f5c4e455b3efc77fee6bf7b6e5d1712b2817ba102db` |
| platform / size | linux/arm64, 78.9 MB on disk |
| reported version | 2.1.0, `edition: community`, `original_edition: floci-always-free` |
| services reported by `/_localstack/health` | 121 `running` |
| run | `docker run -d -p 127.0.0.1:<p>:4566 -p [::1]:<p>:4566 floci/floci:latest` |
| state reset | `POST /_localstack/state/reset` returns 200 and does clear state |

Four containers on 4566–4569, one per shard, reset between every fixture.
Nothing in this spike reached a real AWS endpoint.

**The env the unmodified `provider.tf` needs.** Amendment 32 froze the hcl-raw
workspace to a bare `provider "aws" { region … default_tags … }`, so every
redirection must come from the environment. Three variables are enough for
`terraform` *and* the `aws` CLI in `tests/live_check.py`; two of them are not
obvious:

- `AWS_ENDPOINT_URL=http://127.0.0.1:<p>`, `AWS_ACCESS_KEY_ID=test`,
  `AWS_SECRET_ACCESS_KEY=test`, `AWS_REGION`/`AWS_DEFAULT_REGION=us-east-1`.
  No `skip_credentials_validation` / `skip_requesting_account_id` was needed:
  Floci answers `sts:GetCallerIdentity`.
- `AWS_S3_USE_PATH_STYLE=true` — without it every `aws_s3_bucket` read goes to
  a virtual-hosted host the emulator does not serve.
- `AWS_ENDPOINT_URL_S3_CONTROL=http://localhost:<p>` — the provider reads S3
  bucket tags (which `default_tags` forces on every bucket) through the S3
  Control client, which prefixes the **account id** to the host:
  `Get "http://000000000000.127.0.0.1:4568/v20180820/tags/…": dial tcp:
  lookup 000000000000.127.0.0.1: no such host`. A hostname (`localhost`, which
  resolves as a wildcard suffix) fixes it, which is why the container must also
  publish on `[::1]`. Every S3 spec fails at `apply` without this.

Staging reuses `gates/oracle_falsifiability.py::_run_solve`'s recipe verbatim
(flatten `environment/workspace` into the sandbox root, overlay `tests/`,
`solution/`, `steps/`, rewrite `/logs/verifier` and `/app/project` inside
`tests/static_tiers.sh`), then adds `terraform apply` → second `plan
-detailed-exitcode` → `tests/live_check.py` → `terraform destroy`. Arm:
`hcl_raw` only (the one arm whose toolchain runs from the host). 138 fixtures
= 21 references + 117 broken, across all 20 specs plus the toy.

No spec was skipped for a mid-edit task tree. The only dirty task files at the
time were `caller-identity-arn-as-principal/*/tests/policy.rego` on three arms;
because every fixture is staged from `ba7b13d`, that edit is not in the run.

## Per-spec results

`fx` = fixtures run. `rw` = fixtures whose `reward.txt` agrees with the
fixture's expectation (reference 1.0, broken < 1.0). `apply`/`destroy` = exit 0.
`idem` = second plan empty, over the fixtures that applied. `live` = verdicts
from `tests/live_check.py` (`stub` = the 13 specs whose `live_check.enabled` is
false ship an inert `not_implemented` stub).

| spec | fx | rw | apply | idem | live | destroy | class | first divergence |
|---|--:|--:|--:|--:|---|--:|---|---|
| acm-dns-validation-record-wiring | 5 | 5/5 | 4/5 | 4/4 | stub | 5/5 | FALSE GREEN | cert reaches `ISSUED`/`SUCCESS` with no DNS record in existence |
| apigw-openapi | 3 | 3/3 | 0/3 | — | stub | 3/3 | MATCH (plan-only) | `CreateFunction … zip END header not found` (placeholder zip) |
| apigw-redeploy | 4 | n/a | 4/4 | 0/4 | none | 4/4 | UNSUPPORTED | live check GETs `https://<id>.execute-api.us-east-1.amazonaws.com/` via `urllib` |
| apigwv2-route-settings-zero-vs-unset | 5 | 5/5 | 0/5 | — | stub | 5/5 | MATCH (plan-only) | placeholder zip; burst `0` vs unset round-trips correctly |
| asg-launch-template-tag-propagation | 5 | 5/5 | 3/5 | 3/3 | stub | 3/5 | MATCH (plan-only) | two fixtures are deliberately invalid HCL |
| caller-identity-arn-as-principal | 5 | 4/5 | 4/5 | 4/4 | stub | 5/5 | **FALSE RED** | reference scores **0.0**; `sts` returns `arn:aws:iam::000000000000:root` |
| ddb-gsi-attribute-definitions | 7 | 7/7 | 3/7 | 3/3 | stub | 7/7 | MATCH | `ValidationException: Invalid KeySchema: Some index key attribute have no definition` reproduced |
| ecr-repo-destroy-force-delete | 3 | 1/3 | 3/3 | 3/3 | not_verifiable:2, fail_stale:1 | 0/3 | **UNSUPPORTED** | `InitiateLayerUpload is not supported`; `destroy` HUNG at 180 s |
| ecs-swappiness | 3 | 3/3 | 3/3 | **0/3** | stub | 3/3 | **FALSE RED** | second plan replaces the task definition: `+ linuxParameters = { maxSwap, swappiness }` |
| iam-managed-policy-exclusive-vs-attachment | 10 | 10/10 | 10/10 | 9/10 | stub | 9/10 | MATCH | `DeletePolicy … StatusCode: 409` on one fixture's destroy |
| lambda-alias-tracks-unpublished-latest | 4 | 4/4 | 4/4 | 4/4 | pass:2, fail_stale:2 | 4/4 | **FALSE GREEN** | live check **passes** `alias-still-serves-the-previous-version` |
| lambda-log-group-ownership-and-retention | 5 | 5/5 | 0/5 | — | stub | 5/5 | MATCH (plan-only) | placeholder zip |
| named-resource-replacement | 4 | 3/4 | 4/4 | 4/4 | pass:3, fail_stale:1 | 4/4 | **FALSE GREEN** | `rename-replaces-an-in-use-security-group` scores **1.0**, live pass, converged |
| s3-acl-vs-object-ownership-log-delivery | 6 | 5/6 | 6/6 | 6/6 | fail_stale:5, pass:1 | 6/6 | FALSE GREEN | `PutBucketAcl log-delivery-write` accepted under `BucketOwnerEnforced` |
| s3-bucket-hardening-decomposition | 7 | 7/7 | 6/7 | 6/6 | stub | 7/7 | MATCH | `PutPublicAccessBlock … 404` on the decoy-bucket fixture (AWS agrees) |
| s3-lambda-log-retention | 3 | 3/3 | 0/3 | — | stub | 2/3 | MATCH (plan-only) | placeholder zip |
| s3-notification-authoritative-singleton | 43 | 43/43 | 0/43 | — | stub | 42/43 | FALSE GREEN | `PutBucketNotificationConfiguration` accepts an unpolicied **and a nonexistent** topic |
| s3-notification-custom-resource-tax | 3 | 3/3 | 0/3 | — | stub | 3/3 | MATCH (plan-only) | placeholder zip |
| sfn-jsonata | 4 | 3/4 | 3/4 | 3/3 | not_verifiable:3 | 4/4 | **UNSUPPORTED** | `stepfunctions test-state` resolves `http://sync-127.0.0.1:<p>/` — unreachable |
| singleton-child-resource-clobber | 5 | 5/5 | 4/5 | 4/4 | fail_stale:3, pass:1 | 5/5 | MATCH | whole-document lifecycle PUT clobbers faithfully |
| toy-ssm-parameter (not one of the 20) | 4 | 4/4 | 4/4 | 3/4 | stub | 4/4 | MATCH | one fixture's second plan updates in place |

**Counts over the 20 specs: MATCH 10 · FALSE GREEN 5 · FALSE RED 2 ·
UNSUPPORTED 3.** At the reward level, 132 of 138 fixtures agree; of the six
that do not, three are by design (a live-gated spec whose static half is 1.0
and whose verdict comes from the live check or the teardown tier), one is
unmeasurable through this driver (`apigw-redeploy`'s root `solve.sh` is an
offline two-plan proof and writes no `reward.txt`), and **two are real
divergences** — one false red and one false green.

The emulator never logs an unimplemented operation. `docker logs … | grep -i
'not supported|NotImplemented|Unsupported'` matches **zero** lines across the
whole run; the only signal is the HTTP body (`UnsupportedOperation`). It does
warn once at startup that ECR image operations and EC2 container reconciliation
need a reachable Docker daemon inside the container.

## AWS behaviours the emulator gets wrong or lacks, that the corpus depends on

Each was confirmed by a direct CLI probe against the emulator, not inferred.

1. **EC2 does not enforce security-group dependencies.** `delete-security-group`
   on a group still attached to an interface VPC endpoint returns
   `{"Return": true}`. AWS raises `DependencyViolation`. This is the entire
   `named-resource-replacement` trap, and it is why that spec's broken fixture
   scores a clean **1.0** here.
2. **S3 does not validate a notification destination.**
   `PutBucketNotificationConfiguration` is accepted naming an SNS topic with no
   topic policy, and naming a topic that does not exist. AWS rejects both with
   `InvalidArgument: Unable to validate the following destination
   configurations`. ~20 of `s3-notification-authoritative-singleton`'s fixtures
   are about exactly that statement.
3. **S3 accepts ACLs on a bucket that disables them.**
   `put-bucket-acl --acl log-delivery-write` succeeds on a bucket with
   `ObjectOwnership=BucketOwnerEnforced`, and `get-bucket-acl` then reports the
   `LogDelivery` `WRITE` grant. AWS returns `AccessControlListNotSupported`.
4. **ACM issues without validating.** `request-certificate --validation-method
   DNS` then `describe-certificate` reports `Status: ISSUED`,
   `ValidationStatus: SUCCESS` immediately, with no CNAME published anywhere.
   `aws_acm_certificate_validation` therefore never blocks.
5. **Lambda accepts an alias to `$LATEST`.** `create-alias --function-version
   '$LATEST'` succeeds and `get-alias` reports it. AWS raises a
   `ValidationException`.
6. **STS returns the wrong identity shape.** `get-caller-identity` answers
   `arn:aws:iam::000000000000:root` on account `000000000000` — a root ARN, not
   the assumed-role session ARN every live trial holds.
   `aws_iam_session_context` cannot resolve an issuer role from it, which is why
   `caller-identity-arn-as-principal`'s *reference* is graded FAIL. The
   corpus's own `gates/aws_stub.py` already documents why the assumed-role shape
   matters and answers it correctly; Floci does not.
7. **ECS drops `linuxParameters` on round-trip.** `register-task-definition`
   accepts a container definition with `linuxParameters` and the state refresh
   reads it back without them (and without `default_tags`), so every
   `ecs-swappiness` fixture shows a permanent `forces replacement` diff. The
   lost attribute is the one the spec studies.
8. **ECR has no image plane and cannot be deleted.** `InitiateLayerUpload`,
   `upload-layer-part` and `put-image` return `UnsupportedOperation` ("Backing
   registry unreachable"), so the live check's probe push cannot happen and the
   repository is never non-empty. `DeleteRepository` returns a `ServerException`
   the provider retries with backoff forever: `terraform destroy` was killed at
   180 s on all three fixtures, and an earlier unbounded attempt was still
   retrying at 10 minutes. The `not empty, consider using force_delete` finding
   recorded in `docs/live-results.md` is unreachable, and the gating teardown
   tier would hang rather than fail.
9. **`stepfunctions test-state` is unreachable.** The CLI derives a `sync-`
   prefixed host for that operation, so both `AWS_ENDPOINT_URL` and
   `AWS_ENDPOINT_URL_STEPFUNCTIONS` produce `http://sync-127.0.0.1:<p>/`.
   `sfn-jsonata`'s gating oracle — the Amendment 34 example of a fact only a
   live evaluation API can decide — cannot be run at all.
10. **`apigw-redeploy`'s live check is not redirectable.** It fetches
    `https://<api-id>.execute-api.us-east-1.amazonaws.com/<stage>/` with
    `urllib`, not the SDK, and Floci serves no `execute-api` data plane. There
    is no env var that reaches it.

Things the emulator gets **right** and that matter: DynamoDB's GSI/attribute
`ValidationException` (both directions), S3's whole-document
`PutBucketLifecycleConfiguration` clobber, CloudWatch Logs retention, API
Gateway v2's `0`-vs-unset default route settings, IAM attach/list/put-role-policy,
and REST API Gateway deployment metadata.

## Sidecar cost

| metric | value |
|---|---|
| start → `/_localstack/health` 200 | 0.25 s, 0.26 s, 0.25 s (three cold `docker run`s); 0.92 s on the first run of a freshly pulled image |
| idle RSS | 14.7 MiB |
| RSS after one spec's fixtures | 44–61 MiB |
| image pull | 78.9 MB |
| `terraform apply`, reference workspaces | median **2.0 s**, max 57.3 s (n=21) |
| `terraform apply`, all fixtures | median 1.8 s, p90 16.9 s, max 181.7 s |
| `terraform destroy` | median 2.0 s (excluding the ECR hangs) |

A per-trial sidecar is essentially free: sub-second start, tens of MiB, and an
apply that finishes in seconds where the live `named-resource-replacement`
arms have recorded 10- and 15-minute destroys. Cost is not the obstacle.

## Recommendation

**Not viable as a general trial mode now; viable as an opt-in, per-spec
*authoring* aid for the ten MATCH specs, and nothing more.** The measurement
reproduces Amendment 32's objection rather than retiring it: five of twenty
specs are false-green on the emulator, and the failures land on precisely the
value-rejection behaviours the corpus was built to study — EC2's
`DependencyViolation`, S3's notification-destination validation, S3's
`AccessControlListNotSupported`, ACM's refusal to issue, Lambda's refusal to
alias `$LATEST`. One broken fixture, `named-resource-replacement`'s
`rename-replaces-an-in-use-security-group`, scores a full **1.0** with a
passing gating live check and a converged idempotence tier — the exact
"mocks return false greens" outcome, now with a number on it. Two more specs
are false-*red* (`caller-identity-arn-as-principal`'s reference is graded
FAIL because the emulator's caller identity is a root ARN; `ecs-swappiness`
never converges because ECS drops `linuxParameters`), which would void or
mis-score rows, and three specs — `ecr-repo-destroy-force-delete`,
`sfn-jsonata`, `apigw-redeploy` — cannot be run at all, with the ECR one
hanging `terraform destroy` indefinitely rather than failing. Nine of the ten MATCH
specs are plan-graded (`live_check.enabled: false`), so the emulator only has
to make `terraform plan` succeed, which it does; the tenth,
`singleton-child-resource-clobber`, matched with its gating live check too. All
**53 of 53** fixtures across those ten specs reward exactly as the fixture's
expectation says.
That is a real but narrow win, and it is a win the existing
`gates/aws_stub.py` already delivers for the gates without a container. A
"Floci trials, AWS acceptance" amendment should be declined; a separate, much
smaller amendment allowing Floci as a *local authoring loop* for the
plan-graded specs — never as a grader, never on a published row, and with the
five false-green behaviours listed above written into the entry — is
defensible. Worth revisiting only if Floci gains: an assumed-role STS identity,
lossless ECS `linuxParameters`, EC2 dependency enforcement, S3 notification
destination validation, and an ECR delete that terminates.
