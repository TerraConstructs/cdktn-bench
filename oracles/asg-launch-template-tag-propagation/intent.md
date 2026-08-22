# Oracle intent: Auto Scaling worker fleet whose instances and volumes carry cost-allocation tags

`asg-launch-template-tag-propagation` — generated verbatim from `specs/asg-launch-template-tag-propagation.yaml`'s `oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single natural-language source of truth that both `../rego/asg-launch-template-tag-propagation/policy.rego` and `../cfn-guard/asg-launch-template-tag-propagation/policy.guard` must encode at the same strictness — the oracle-equivalence CI (Slice E) uses this file as the human-reviewable reference when checking that.

**Do not hand-edit this file.** It is regenerated from the spec on every `emit_oracles` call; edit `oracle.intent` in `specs/asg-launch-template-tag-propagation.yaml` instead.

---

An Auto Scaling group of EC2 instances exists, sized to a minimum of 2 and a maximum of 6, launching from a launch template whose instances run AMI {{WORKER_AMI_ID}} on a t3.small instance type in a VPC this configuration creates. Every instance the group launches carries the tags CostCenter=platform-42 and Environment=prod -- reached via the Auto Scaling group's own tag-propagation mechanism (`propagate_at_launch`/PropagateAtLaunch = true), or via the launch template's own `instance`-resourceType tag specification, or both; at least one of the two must be present for each key. Every EBS volume the group's instances launch with also carries both tags -- reachable ONLY through the launch template's `volume`-resourceType tag specification (Auto Scaling's own tag-propagation mechanism never reaches EBS volumes, regardless of `propagate_at_launch`), so this half has no alternative mechanism to accept.
