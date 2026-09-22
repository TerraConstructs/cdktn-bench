# cdktn-bench hcl-modules arm — workspace entrypoint (agent-owned).
#
# This is the starting scaffold baked into every generated task's agent
# container (see ../../README.md and ../../../../specs/SCHEMA.md §2.4). The
# generator overwrites this file wholesale per scenario — it is the ONLY file
# in this workspace the agent is expected to (fully) rewrite.
#
# The provider bootstrap lives in ./provider.tf instead, on purpose: this file
# is fully rewritten by a normal agent solution, so anything an agent might
# legitimately delete cannot live here. Do not modify provider.tf.
#
# Registry modules resolve offline through the tf-registry sidecar, so a
# `module` block is written exactly as it would be against the public registry:
#
#   module "bucket" {
#     source  = "terraform-aws-modules/s3-bucket/aws"
#     version = "5.16.1"
#   }
#
# Only the vendored module@version set is served; anything else fails `init`
# with a message listing what is available. A `source` pointing at a local path
# under /opt is not a registry source and is denied by the verifier
# (DECISIONS.md Amendment 46 (c)).
#
# TODO(agent): add your module and resource blocks below. See the task
# instruction for what to create.
