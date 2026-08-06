# Oracle intent: ECS EC2 task definition: tuned container memory swappiness

`ecs-swappiness` — generated verbatim from `specs/ecs-swappiness.yaml`'s `oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single natural-language source of truth that both `../rego/ecs-swappiness/policy.rego` and `../cfn-guard/ecs-swappiness/policy.guard` must encode at the same strictness — the oracle-equivalence CI (Slice E) uses this file as the human-reviewable reference when checking that.

**Do not hand-edit this file.** It is regenerated from the spec on every `emit_oracles` call; edit `oracle.intent` in `specs/ecs-swappiness.yaml` instead.

---

Exactly one AWS::ECS::TaskDefinition exists, compatible with the EC2 launch type, containing exactly one container definition. That container's Linux parameters set memory swappiness to exactly 42, nested at container.linuxParameters.swappiness — not at the task definition's top level, not at the container's own top level, and not under any other key. The same container's Linux parameters also set maxSwap (the container's total swap memory), because AWS ECS silently ignores swappiness whenever maxSwap is absent: the tuned swappiness value must be EFFECTIVE, not merely present in the artifact.
