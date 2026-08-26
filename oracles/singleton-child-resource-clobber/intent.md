# Oracle intent: Add a rule to a bucket whose storage-rule document is an authoritative singleton child resource

`singleton-child-resource-clobber` — generated verbatim from `specs/singleton-child-resource-clobber.yaml`'s `oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single natural-language source of truth that both `../rego/singleton-child-resource-clobber/policy.rego` and `../cfn-guard/singleton-child-resource-clobber/policy.guard` must encode at the same strictness — the oracle-equivalence CI (Slice E) uses this file as the human-reviewable reference when checking that.

**Do not hand-edit this file.** It is regenerated from the spec on every `emit_oracles` call; edit `oracle.intent` in `specs/singleton-child-resource-clobber.yaml` instead.

---

A correct solution leaves this workspace deploying the same bucket it
described before, with exactly one thing added: objects under `exports/`
move to Glacier Instant Retrieval 90 days after they are created, and the
other team's 30-day expiry of `logs/` is untouched and still in effect.

Four things are graded, in four places, and the split is deliberate:

1. TIER 0 (static, every arm). The new rule is there, with the requested
   prefix, storage class and day count; the existing rule is still there,
   still deleting `logs/` after 30 days; the workspace still has exactly
   one bucket; and — on the Terraform-shaped arms — exactly one
   `aws_s3_bucket_lifecycle_configuration` resource. The last of those is
   the ONLY static check that distinguishes the headline mistake from a
   correct answer, because both rules are present in the artifact either
   way. The first of them is what makes the DO-NOTHING answer fail: the
   seed already deploys green, so without an assert about the new rule an
   agent that changed nothing would score 1.0. See
   `solution/broken/seed-unchanged/`, which exists to keep proving that.

2. TIER 1 (Rego / cfn-guard, every arm). No rule in the document may be
   left un-enabled. A quantified statement over a collection, not a pinned
   value.

3. LIVE (`tests/live_check.py`, gating). Whether the change ACTUALLY
   LANDED, read from the one document the S3 API really returns for this
   bucket. This is the only instrument in the stack that can tell "the file
   says both rules" from "the account has both rules", and the difference
   between those two sentences is what the headline catch produces. It is
   also the only one that can see a change that was authored and never
   rolled out, which the prompt asks for in as many words.

4. IDEMPOTENCE (gating). Two documents fighting over one API never settle:
   the next plan is not empty. A change that has to be re-applied to stay
   applied is not a change that landed.

What is deliberately NOT graded: how many resources each arm's expansion
produced; whether the rules are expressed as an L2 prop, an L2 child
construct or raw HCL; the id the agent gives its NEW rule (only the
existing rule's id is pinned, because that one is not the agent's to
rename); and anything about the bucket beyond its identity.
