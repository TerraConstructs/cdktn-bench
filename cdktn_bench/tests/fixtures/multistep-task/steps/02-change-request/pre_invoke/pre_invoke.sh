#!/usr/bin/env bash
# The cdktn extension: a per-step, credential-staged harness action, run by
# CdktnMultiStepTrial._run_step_pre_invoke via aws-bench's own ScriptRunner
# with ~/.aws/credentials staged for the task's pre_invoke role.
#
# This is where deploy-of-prior-step-work and out-of-band ("someone changed it
# in the console") drift injection live. Its placeholder.json feeds
# {{...}} tokens into THIS step's instruction.
#
# Toy version: no AWS calls, just proves the wiring and the placeholder hand-off.
set -euo pipefail
mkdir -p /logs/pre_invoke
printf '{"ToyParameterName": "/cdktn-bench/toy"}\n' > /logs/pre_invoke/placeholder.json
