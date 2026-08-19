#!/usr/bin/env bash
# Step-1 oracle. Lives under steps/01-initial/tests/, never in the shared
# tests/ — harbor/verifier/verifier.py::_resolve_tests uploads the shared
# tests/ during EVERY step's verification, so a step-specific oracle there
# would leak that step's intent into earlier steps' containers.
set -euo pipefail
grep -q 'initial' app/main.tf && echo 1.0 > /logs/verifier/reward.txt
