# Shared tests/ — deliberately EMPTY of oracle material

Generated — generator/gen.py, from specs/apigw-redeploy.yaml. Do not
hand-edit; regenerate instead.

This is a MULTI-STEP task (`[[steps]]` in `task.toml`). Every step's
oracle lives in `steps/<name>/tests/`, never here.

Why: Harbor uploads this directory into the container's `/tests`
during **every** step's verification, and only empties `/tests` at the
start of the **next** step's verification — i.e. after that step's
agent has already run. Oracle material placed here is therefore
readable by a later step's agent. Keeping it empty is what makes the
no-foreshadowing property hold for the grader as well as the prompt
(DECISIONS.md Amendment 26 §7 rule 1;
docs/design/multistep-trial-investigation.md §5;
docs/prompt-decomposition-audit.md §6).

This README itself is step-agnostic — it names no route, no resource,
no assertion, and no step but the rule.
