#!/bin/bash
# Reference oracle for cdktn-smoke/anchor-write-file. Run by Harbor's
# OracleAgent (`-a oracle`) in place of a real agent.
set -euo pipefail

mkdir -p /logs/agent
printf '%s' "cdktn-bench-anchor-smoke-ok" > /logs/agent/agent-output.txt
