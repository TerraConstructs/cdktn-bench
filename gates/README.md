# gates

The three-gate integrity pattern borrowed from lex00 (build plan Phase 0, the "single
most valuable thing in the fork"):

1. **preflight** — the arm's toolchain actually works in its container
   (`tsc --version`, `cdk --version`, `terraform version`, provider mirror warm).
   Driven by `make preflight` at the repo root.
2. **audit** — the trial *actually ran the substrate's toolchain*, not a shortcut.
   Parses `agent/trajectory.json` for `tsc`/`cdk synth` / `terraform validate|plan`
   invocations; a green trial that never ran the arm's toolchain is invalid, not
   scored. Rationale: lex00's first round scored CDK 11/15 while 0-2 of 24 trials ever
   ran `cdk`.
3. **emit-result** — refuses to emit a result record for an invalid run (validity is a
   separate class from a low score; e.g. a `cdk synth` OOM is infrastructure-invalid,
   never a scored CDK failure).

Also owns the **equipping hash** (SHA of instruction.md + skill/MCP config + Docker
image digest) written into every result record, so results can never be silently
pooled across different equippings.

Populated in Slice B.
