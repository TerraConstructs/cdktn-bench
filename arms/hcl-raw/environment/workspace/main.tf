# cdktn-bench hcl-raw arm — workspace entrypoint (agent-owned).
#
# This is the starting scaffold baked into every generated task's agent
# container (see ../../README.md and ../../../../specs/SCHEMA.md §2.4's
# hcl_raw output_contract row). The generator (Slice C) overwrites this
# file wholesale per scenario — it is the ONLY file in this workspace the
# agent is expected to (fully) rewrite.
#
# The provider bootstrap lives in ./provider.tf instead, on purpose: this
# file is fully rewritten by a normal agent solution (there is no reason
# for hand-written HCL to preserve boilerplate the agent never authored and
# the instruction never mentions), so anything an agent might legitimately
# delete cannot live here. Do not modify provider.tf.
#
# TODO(agent): add your resource blocks below. See the task instruction for
# what to create.
