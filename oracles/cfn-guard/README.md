# oracles/cfn-guard

cfn-guard rules graded against the CDK arm's synthesized CloudFormation template
(`cdk synth` output), per `docs/aws-bench-guide.md` §7c Level-1 verifier pattern.

One `.guard` ruleset per scenario catch, equivalent in strictness to the matching
`../rego/` policy for the same scenario — enforced by the oracle-equivalence CI
(Slice E), which runs both oracle tiers against all arms' reference solutions on every
commit and fails on divergent strictness (build plan Phase 1).

Populated in Slice D.
