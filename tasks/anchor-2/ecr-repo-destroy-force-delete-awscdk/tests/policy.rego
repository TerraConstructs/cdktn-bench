# Hand-authored awscdk tier-1 bundle (ROADMAP.md M8: OPA/Rego grades tier 1
# on every arm). `input` is the awscdk arm's synthesized CloudFormation
# template, cdk.out/ScenarioStack.template.json -- resources live under
# `input.Resources[<LogicalId>]` with `.Type`/`.Properties`. Intent:
# oracles/ecr-repo-destroy-force-delete/intent.md.
#
# Encodes the one awscdk tier-"1" assert, repository-empties-natively-on-
# delete: every AWS::ECR::Repository carries `EmptyOnDelete: true`, and no
# `Custom::ECRAutoDeleteImages` resource exists anywhere in the template --
# the registry's own native behaviour, not an added custom-resource Lambda.
# The TF-shaped arms have no tier-1 assert for this fact at all; there it is
# graded by the gating teardown tier, so oracles/rego/<id>/policy.rego is a
# deliberate stub and this file has no strictness twin to mirror.
#
# not_verifiable: empty. Every fact above is a literal in a static template.
#
# Strictness vs the retired oracles/cfn-guard/<id>/policy.guard: none. The
# three rules below are that policy's repository_exists,
# repository_empties_on_delete and no_auto_delete_images_custom_resource,
# one for one, with the same verdict on every fixture.

package cdktn_bench.ecr_repo_destroy_force_delete

import rego.v1

repositories[lid] := r if {
	some lid, r in input.Resources
	r.Type == "AWS::ECR::Repository"
}

# Fail-closed cover for the rule below, whose body is vacuous on a template
# holding no repository at all.
deny contains msg if {
	count(repositories) == 0
	msg := "no AWS::ECR::Repository resource exists in the template"
}

deny contains msg if {
	some lid, r in repositories
	object.get(r, ["Properties", "EmptyOnDelete"], null) != true
	msg := sprintf(
		"AWS::ECR::Repository %q (logical id) does not set Properties.EmptyOnDelete to true -- deleting a repository that still holds images fails without it, so the stack cannot be torn down cleanly",
		[lid],
	)
}

# A sibling of the repository, not a child, so this is a template-wide
# absence check: the deprecated `autoDeleteImages` prop meets the same
# teardown requirement by deploying a Lambda, a role and a policy, which
# the intent refuses -- the native property needs none of them.
deny contains msg if {
	some lid, r in input.Resources
	r.Type == "Custom::ECRAutoDeleteImages"
	msg := sprintf(
		"resource %q (logical id) is a Custom::ECRAutoDeleteImages custom resource -- the repository must empty itself on delete through ECR's own EmptyOnDelete, not through an added custom-resource Lambda",
		[lid],
	)
}

not_verifiable contains msg if {
	false
	msg := ""
}
