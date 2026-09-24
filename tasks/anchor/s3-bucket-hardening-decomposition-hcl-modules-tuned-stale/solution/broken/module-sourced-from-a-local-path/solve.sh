#!/usr/bin/env bash
# EXTRA NEGATIVE FIXTURE -- no catch of its own, and that is deliberate: this
# is not a mistake about S3, it is the arm's own rule (DECISIONS.md Amendment
# 46 (c)). Every call the ROOT module makes must resolve from the module
# registry this environment serves; a copy of a module called by local path is
# not composition, and a plan built that way is indistinguishable from a
# composed one.
#
# The call below names a module this script writes into the workspace. What
# proves the deny fired, rather than the tiers failing on a bucket with none of
# the four controls, is the TRANSCRIPT: `MODULE SOURCES FAILED` and no
# `== summary: tier0_pass=... ==` line at all, because the run stops before
# either tier. That the deny also fires on a workspace whose tiers WOULD BOTH
# PASS is held by generator/tests/test_hcl_modules_verifier.py, which stages
# exactly that; a fixture cannot, because a local module that reproduced the
# whole composition would be a second copy of the vendored tree in this repo.
#
# Expected: 0.0, at the toolchain tier -- the same shape a failed
# `terraform plan` reports -- with /logs/verifier/module-source-denied written.
set -euo pipefail

mkdir -p vendored-s3-bucket
cat > vendored-s3-bucket/main.tf <<'HCL'
variable "bucket" {
  type = string
}

resource "aws_s3_bucket" "this" {
  bucket = var.bucket
}
HCL

cat > main.tf <<'HCL'
module "archive" {
  source = "./vendored-s3-bucket"

  bucket = "cdktn-bench-document-archive"
}
HCL

bash tests/static_tiers.sh
