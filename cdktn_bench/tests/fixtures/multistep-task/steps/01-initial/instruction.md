<!-- canary: cdktn-bench toy fixture, not a real task -->

Create `app/main.tf` declaring a single `aws_ssm_parameter` named
`/cdktn-bench/toy` with the value `initial`.

This prompt must be self-contained: a fresh agent session runs each step
(DECISIONS.md Amendment 26), so nothing from a prior step's reasoning survives —
only the workspace does.
