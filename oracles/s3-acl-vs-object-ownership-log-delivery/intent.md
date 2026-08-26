# Oracle intent: Disable bucket ACLs on a log-delivery destination bucket without losing log delivery

`s3-acl-vs-object-ownership-log-delivery` — generated verbatim from `specs/s3-acl-vs-object-ownership-log-delivery.yaml`'s `oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single natural-language source of truth that both `../rego/s3-acl-vs-object-ownership-log-delivery/policy.rego` and `../cfn-guard/s3-acl-vs-object-ownership-log-delivery/policy.guard` must encode at the same strictness — the oracle-equivalence CI (Slice E) uses this file as the human-reviewable reference when checking that.

**Do not hand-edit this file.** It is regenerated from the spec on every `emit_oracles` call; edit `oracle.intent` in `specs/s3-acl-vs-object-ownership-log-delivery.yaml` instead.

---

A correct solution leaves this workspace deploying the same system it
described before -- an application bucket whose S3 server access logs are
delivered to a second bucket under the `app-data/` prefix -- with one thing
changed: the destination bucket no longer uses access control lists, and
the authorization that log delivery depends on has moved from a bucket ACL
to a bucket policy.

Four things are graded, in four places, and the split is deliberate.

1. TIER 0 (static, every arm). The application bucket still declares a
   logging configuration pointing at a bucket this configuration creates,
   under the `app-data/` prefix -- i.e. the requirement the ticket's second
   sentence protects was not deleted on the way past.

2. TIER 0 (static, awscdk only). The destination bucket's policy grants
   `s3:PutObject` to the `logging.s3.amazonaws.com` service principal.
   Declared for one arm only, and that asymmetry is an artifact-shape fact
   rather than a choice: on CloudFormation the policy document is literal
   JSON in the template; on both Terraform arms the same document is either
   gone from the artifact entirely (hcl_raw) or readable only conditionally
   (terraconstructs) -- see 3 and 4.

3. TIER 1 (Rego / cfn-guard). Two quantified claims, which is exactly what
   separates this tier from tier 0 -- a jq path pins one value at one path;
   neither of these is that shape:
     * (every arm) NO ownership control anywhere in this workspace may
       leave ACLs enabled -- not `ObjectWriter`, not
       `BucketOwnerPreferred`, on any bucket. THIS IS WHAT MAKES THE
       DO-NOTHING ANSWER FAIL on the Terraform arms: the seed already
       deploys green, so without it an agent that changed nothing would
       score 1.0. See `solution/broken/seed-unchanged/`, which exists
       precisely to keep proving that.
     * (Terraform arms) the destination bucket must declare a bucket policy
       at all, and IF that document is readable from the artifact it must
       name the logging service principal. The conditional half is why this
       cannot be a jq path: readability differs by arm and by the shape the
       agent chose, and an unconditional path would score a correct
       solution 0.0 on whichever shape it failed to anticipate.

   This scenario deliberately does NOT also declare a tier-0 twin of the
   ownership claim, and the reason is recorded rather than assumed: it did,
   until `make tier1-coverage` pointed out that a tier-1 assert whose only
   negative fixture trips a tier-0 assert first is a tier-1 assert nothing
   falsifies. One claim, one tier, one fixture that really exercises it.

4. LIVE (`tests/live_check.py`, gating). Whether log delivery ACTUALLY
   STILL WORKS. This tier does not ask whether a property is set. It reads
   the deployed state of both buckets and answers the authorization
   question AWS itself answers: with ACLs disabled, is
   `logging.s3.amazonaws.com` permitted to `s3:PutObject` into
   `s3://<destination>/app-data/...`? It evaluates the real bucket policy
   (principals, actions, resource ARN patterns, and Deny statements) rather
   than pattern-matching it, checks that the deployed logging configuration
   still names this bucket and prefix, checks that the ACL grant is really
   gone, and finally re-drives S3's own `PutBucketLogging` validator
   against the configuration it just read. On hcl_raw it is the ONLY tier
   that can see a wrong grant at all. On every arm it is the only tier that
   can see whether the change LANDED -- a plan that was never applied, or
   an apply that failed part-way, is indistinguishable from a successful
   one in the graded artifact -- and the only tier that would notice an
   ownership control deleted outright rather than corrected, which no
   remaining static assert covers.

What is deliberately NOT graded: how many resources each arm's expansion
produced; whether the bucket policy is written as `jsonencode`, a
`data "aws_iam_policy_document"`, an L2 `addToResourcePolicy` call or a
literal document; whether the `aws_s3_bucket_acl` resource is deleted from
the configuration or retained with a non-granting value; and how many
applies it took to get there. The arms are compared on the declared
behavioural facts only.
