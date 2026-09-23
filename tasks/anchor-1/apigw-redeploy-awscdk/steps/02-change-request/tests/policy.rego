# Hand-authored awscdk tier-1 bundle (ROADMAP.md M8: OPA/Rego grades tier 1
# on every arm). `input` is the awscdk arm's synthesized CloudFormation
# template, cdk.out/ScenarioStack.template.json. Intent:
# oracles/apigw-redeploy/intent.md.
#
# Encodes the one awscdk tier-"1" assert, deployment-depends-on-all-methods:
# every AWS::ApiGateway::Method's LOGICAL ID appears in every
# AWS::ApiGateway::Deployment's DependsOn -- an identity join, the CFN twin
# of the TF policy's per-address coverage check. Same rule body as
# oracles/rego-cfn/apigw-openapi/policy.rego's; that scenario's
# route-count-correct is not reused, apigw-redeploy declares no such catch.
#
# not_verifiable: empty. DependsOn holds literal logical ids.
#
# Strictness vs the retired oracles/cfn-guard/<id>/policy.guard: that policy
# proxied the fact as `count(DependsOn.*) >= count(Methods)` and inherited
# apigw-openapi's recorded gap -- an escape-hatch CfnDeployment naming 3
# NON-method resources passed it. The join closes it. No verdict changes.

package cdktn_bench.apigw_redeploy

import rego.v1

methods[lid] := r if {
	some lid, r in input.Resources
	r.Type == "AWS::ApiGateway::Method"
}

deployments[lid] := r if {
	some lid, r in input.Resources
	r.Type == "AWS::ApiGateway::Deployment"
}

# CloudFormation accepts DependsOn as a single logical id or a list of them.
depends_on(r) := s if {
	d := object.get(r, "DependsOn", [])
	is_array(d)
	s := {x | some x in d}
}

depends_on(r) := s if {
	d := object.get(r, "DependsOn", [])
	is_string(d)
	s := {d}
}

# Fails closed if methods exist but no Deployment resource is present at all.
deny contains msg if {
	count(methods) > 0
	count(deployments) == 0
	msg := "API Gateway methods exist but no AWS::ApiGateway::Deployment resource was found in the template"
}

deny contains msg if {
	some dlid, dep in deployments
	missing := {mlid |
		some mlid, _ in methods
		not mlid in depends_on(dep)
	}
	count(missing) > 0
	msg := sprintf(
		"AWS::ApiGateway::Deployment %q (logical id) does not name method(s) %v in its DependsOn -- the classic API Gateway deployment race: the deployment can be created before, or without ever picking up, those routes",
		[dlid, missing],
	)
}

not_verifiable contains msg if {
	false
	msg := ""
}
