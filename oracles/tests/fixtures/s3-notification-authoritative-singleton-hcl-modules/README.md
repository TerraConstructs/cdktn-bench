# hcl_modules plan fixtures — s3-notification-authoritative-singleton

Real `terraform show -json` plans from the vendored
`terraform-aws-modules` tree (`arms/hcl-modules/environment/modules`), run
through the plan normaliser (`generator/verify_py.py::normalise_plan`) and then
TRIMMED. One file per `tasks/anchor/s3-notification-authoritative-singleton-hcl-modules/solution/**`
entry, named after it. **`_hcl` is absent from every one of them, which is the
point**: no merge runs on this arm (`specs/SCHEMA.md` §4.6), so the policy has
to reach every verdict from the normalised plan alone.

## What the trim removes, and why the files are still evidence

`prior_state`, `resource_changes`, `provider_config`, module `variables`; every
resource whose type no rule in the policy reads; every `expressions` key,
`values` key and `x_unresolved` mark for an attribute no rule reads; every
module `outputs` entry no module-call argument references; and every module-body
configuration node that governs no planned instance — which is the policy's own
`_node_is_planned` filter, so it can change no verdict.

The trim was verified rather than assumed: the `deny` and `not_verifiable` sets
of every file here are IDENTICAL to those of the untrimmed plan it came from.
Re-collect the untrimmed originals with
`make normaliser-parity SPEC=specs/s3-notification-authoritative-singleton.yaml OUT=<dir>`.
