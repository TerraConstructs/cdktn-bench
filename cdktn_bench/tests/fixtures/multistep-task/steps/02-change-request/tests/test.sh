#!/usr/bin/env bash
set -euo pipefail
grep -q 'changed' app/main.tf && echo 1.0 > /logs/verifier/reward.txt
