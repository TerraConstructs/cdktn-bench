#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `alias-still-serves-the-previous-version`, whose predicted_tier_caught is
# "live" on THIS arm (and "0" on the two Terraform arms -- see those arms' own
# fixtures, which are ordinary reward-0.0 negatives).
#
# THE MISTAKE: the plausible, competent-looking answer. It makes exactly the
# change the ticket asks for -- `QUOTE_CURRENCY` becomes `USD` -- and touches
# nothing else. It compiles. It synthesizes. It deploys CLEANLY. It satisfies
# every tier-0 assert. And the `AWS::Lambda::Version` resource it leaves alone
# has only one property (`FunctionName`), which did not change, so CloudFormation
# issues no update for it, no new version is published, and the alias goes on
# naming version 1 -- whose immutable snapshot still says `EUR`. Every caller
# that goes through the alias, which the ticket says is all of them, keeps
# getting euros.
#
# WHAT THIS FIXTURE MUST PROVE, AND HOW
# =====================================
# A "live"-tier catch is only falsified if its OFFLINE run MECHANICALLY
# DEMONSTRATES the static-indistinguishability property it claims, rather than
# asserting it in a comment (gates/oracle_falsifiability.py's `live` branch,
# LIVE_ONLY_CONFIRMED_MARKER; SCHEMA.md §3). So, offline, with no credentials
# and no account, this script:
#
#   1. synthesizes the REFERENCE shape (`version: quoteService.currentVersion`);
#   2. synthesizes THIS shape (a stand-alone `new lambda.Version(...)`);
#   3. CANONICALISES both templates and requires them to be byte-identical.
#
# The canonicalisation is stated precisely, because a proof whose normalisation
# is vague proves nothing:
#
#   (a) every CloudFormation LOGICAL ID is rewritten to `<Type>#<n>` --
#       n being its index among the resources of that Type, in sorted-id order
#       -- and the rewrite is applied to the WHOLE document, so every `Ref`,
#       `Fn::GetAtt` and `DependsOn` that names it is rewritten with it. This is
#       what erases the single real difference: aws-cdk-lib stamps a hash of the
#       function's own configuration into `currentVersion`'s logical id
#       (`QuoteServiceCurrentVersion<hash>`) where a stand-alone `Version`
#       construct's id comes from its construct path (`ReleasedVersion<hash>`).
#   (b) every `Metadata` block is dropped. That is CDK's own provenance
#       (`aws:cdk:path`, `aws:cdk:do-not-refactor`) -- the construct id the
#       AUTHOR typed, not a fact about the infrastructure.
#
# WHAT THE PROOF DOES AND DOES NOT CLAIM. It does NOT claim that no string
# anywhere differs -- (a) and (b) are exactly the strings that do. It claims
# that everything an oracle grading INFRASTRUCTURE can address is identical:
# same resource Types, same Properties, same graph. `generator/jsonpath_jq.py`
# has no bracket-quoted-key segment and therefore cannot address a logical id at
# all, so no `structural_assert` in this repo can express the residual
# difference even by accident; and a Rego/cfn-guard rule that keyed on the
# substring `CurrentVersion` inside a CDK-generated identifier would bind this
# scenario's oracle to aws-cdk-lib's private naming and would score 0.0 a
# correct solution that publishes versions any other way -- the same refusal
# specs/named-resource-replacement.yaml records for pinning a CDK logical id.
#
# IF STEP 3 EVER FAILS, this fixture goes red and `make falsifiability` with it,
# which is the point: it means aws-cdk-lib has started emitting some
# property-level difference between the two shapes, and this catch must be
# re-tiered from "live" to "0" with a real static assert rather than silently
# continuing to claim an invisibility it no longer has.
#
# Expected verdict: reward 1.0 (the static tiers genuinely cannot see this) AND
# the marker on stdout. Both are required; either alone is not falsification.
set -euo pipefail

MARKER="CDKTN_BENCH_LIVE_ONLY_CONFIRMED"
PROBE_REF="${TMPDIR:-/tmp}/laa-probe-ref.$$"
PROBE_BAD="${TMPDIR:-/tmp}/laa-probe-bad.$$"
CANON="${TMPDIR:-/tmp}/laa-canon.$$.py"
trap 'rm -rf "$PROBE_REF" "$PROBE_BAD" "$CANON"' EXIT

mkdir -p lib

# --- the two shapes ---------------------------------------------------------
write_reference_shape() {
  cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const quoteService = new lambda.Function(this, "QuoteService", {
      functionName: "cdktn-bench-quote-service",
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        [
          "exports.handler = async () => ({",
          "  statusCode: 200,",
          "  body: JSON.stringify({ currency: process.env.QUOTE_CURRENCY }),",
          "});",
        ].join("\n"),
      ),
      environment: {
        QUOTE_CURRENCY: "USD",
      },
    });

    new lambda.Alias(this, "LiveAlias", {
      aliasName: "quote-service-live",
      version: quoteService.currentVersion,
    });
  }
}
TS
}

write_fixture_shape() {
  cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const quoteService = new lambda.Function(this, "QuoteService", {
      functionName: "cdktn-bench-quote-service",
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        [
          "exports.handler = async () => ({",
          "  statusCode: 200,",
          "  body: JSON.stringify({ currency: process.env.QUOTE_CURRENCY }),",
          "});",
        ].join("\n"),
      ),
      environment: {
        QUOTE_CURRENCY: "USD",
      },
    });

    const releasedVersion = new lambda.Version(this, "ReleasedVersion", {
      lambda: quoteService,
    });

    new lambda.Alias(this, "LiveAlias", {
      aliasName: "quote-service-live",
      version: releasedVersion,
    });
  }
}
TS
}

# --- the canonicaliser ------------------------------------------------------
cat > "$CANON" <<'PY'
import json
import sys

template = json.load(open(sys.argv[1]))
resources = template.get("Resources", {})

# (a) logical id -> "<Type>#<n>", applied to the WHOLE document text so every
#     Ref / Fn::GetAtt / DependsOn that names an id is rewritten with it.
by_type: dict[str, int] = {}
mapping: dict[str, str] = {}
for logical_id in sorted(resources):
    kind = resources[logical_id].get("Type", "?")
    mapping[logical_id] = f"{kind}#{by_type.get(kind, 0)}"
    by_type[kind] = by_type.get(kind, 0) + 1

text = json.dumps(template)
for logical_id in sorted(mapping, key=len, reverse=True):  # longest first
    text = text.replace(logical_id, mapping[logical_id])
doc = json.loads(text)


# (b) drop CDK's own provenance.
def strip(node):
    if isinstance(node, list):
        return [strip(x) for x in node]
    if isinstance(node, dict):
        return {k: strip(v) for k, v in sorted(node.items()) if k != "Metadata"}
    return node


print(json.dumps(strip(doc), indent=2, sort_keys=True))
PY

# --- the mechanical static-indistinguishability proof -----------------------
echo "== static-indistinguishability probe: synthesizing both shapes =="
write_reference_shape
npx cdk synth --no-lookups --quiet -o "$PROBE_REF" >/dev/null
write_fixture_shape
npx cdk synth --no-lookups --quiet -o "$PROBE_BAD" >/dev/null

python3 "$CANON" "$PROBE_REF/ScenarioStack.template.json" > "$PROBE_REF/canon.json"
python3 "$CANON" "$PROBE_BAD/ScenarioStack.template.json" > "$PROBE_BAD/canon.json"

if cmp -s "$PROBE_REF/canon.json" "$PROBE_BAD/canon.json"; then
  echo "$MARKER: the CloudFormation templates synthesized from"
  echo "  'version: quoteService.currentVersion' and from a stand-alone"
  echo "  'new lambda.Version(...)' are BYTE-IDENTICAL once every logical id is"
  echo "  rewritten to <Type>#<n> and CDK's own Metadata is dropped. Same"
  echo "  resource Types, same Properties, same graph. The only thing that"
  echo "  differs is an identifier aws-cdk-lib generates, which"
  echo "  generator/jsonpath_jq.py cannot address at all (it has no"
  echo "  bracket-quoted-key segment), so no structural_assert can distinguish"
  echo "  the reference solution from this fixture. The catch is live-only on"
  echo "  this arm by construction, not by oracle weakness."
else
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the graded artifact DOES" >&2
  echo "differ between the currentVersion and stand-alone-Version shapes, in a" >&2
  echo "way that survives logical-id canonicalisation. This catch is no longer" >&2
  echo "'live'-tier on awscdk -- re-tier it in the spec and add a real static" >&2
  echo "assert. Diff:" >&2
  diff "$PROBE_REF/canon.json" "$PROBE_BAD/canon.json" >&2 || true
fi

# --- the fixture itself: the naive change, left in place for grading --------
write_fixture_shape

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: this deploy is EXPECTED to succeed and to leave the alias behind =="
  # FIXTURE SELF-PROOF, the same discipline specs/named-resource-replacement's
  # own live fixture carries (finding M5): `--expect stale` alone CANNOT tell
  # this catch from a no-op, because workspace_seed.deploy has the harness put
  # the euro-serving alias in the account before this script starts -- so
  # `fail_stale` is true BY CONSTRUCTION until something changes it. The
  # discriminating fact here is the OPPOSITE of the sibling scenario's: the
  # deploy must SUCCEED (exit 0) and the alias must STILL be stale afterwards.
  # A deploy that failed would also reach `fail_stale`, and laundering that into
  # a green `--expect stale` would let a broken toolchain masquerade as this
  # catch.
  DEPLOY_LOG=/tmp/lambda-alias-broken-awscdk.log
  set +e
  npx cdk deploy --require-approval never ScenarioStack > "$DEPLOY_LOG" 2>&1
  deploy_rc=$?
  set -e
  cat "$DEPLOY_LOG"
  if [ "$deploy_rc" -ne 0 ]; then
    echo "FIXTURE PROOF FAILED: the deploy exited $deploy_rc." >&2
    echo "This fixture exists to pin a change that DEPLOYS CLEANLY and is still" >&2
    echo "wrong. A failed deploy also produces live_check's 'fail_stale', so" >&2
    echo "accepting it here would let any broken toolchain wear this catch's" >&2
    echo "costume. Log: $DEPLOY_LOG" >&2
    exit 1
  fi
  echo "== deploy succeeded, as this fixture requires; now asking the account =="
  python3 tests/live_check.py --expect stale
fi

exec bash tests/static_tiers.sh
