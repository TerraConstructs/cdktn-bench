#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# terraconstructs 0.2.13's compute.autoscaling.AutoScalingGroup ALWAYS
# builds a real LaunchTemplate CHILD construct of the AutoScalingGroup
# itself (read directly from lib/aws/compute/auto-scaling/
# auto-scaling-group.js -- its own source comment states
# "aws_autoscaling_group only supports launch_template/
# mixed_instances_policy ... A LaunchTemplate is therefore ALWAYS
# synthesized here from these launch-configuration-style props ...
# unconditionally the default in this port"), even when vpc/instanceType/
# machineImage are passed directly with no explicit `launchTemplate` prop.
# Because that LaunchTemplate is a genuine CHILD construct of `fleet`, a
# SINGLE `Tags.of(fleet).add(...)` aspect call cascades to BOTH the ASG's
# own tag-propagation blocks AND the launch template's own
# tag_specifications (instance AND volume resourceTypes,
# lib/aws/compute/launch-template.js) with no separate LaunchTemplate
# construction step required at all -- confirmed directly against this
# pinned package's own source.
#
# CORRECTED 2026-08-21 (this scenario's own adversarial verifier round):
# an earlier draft of this comment (and of
# specs/asg-launch-template-tag-propagation.yaml's own arms.terraconstructs
# .reason) contrasted this behavior with a claim that aws-cdk-lib's own
# AutoScalingGroup ALWAYS falls back to a legacy, non-taggable
# AWS::AutoScaling::LaunchConfiguration on its default construction path.
# That contrast is FALSE for this harness: the awscdk arm's generated
# cdk.json enables `generateLaunchTemplateInsteadOfLaunchConfig`, so
# awscdk's own default construction path ALSO builds a real LaunchTemplate
# child reachable from one `Tags.of()` call (see the spec's own header
# comment, evidence point 4, and the awscdk arm's own solve.sh for the
# repro). This arm's own behavior above is unchanged and still correct --
# only the CONTRAST with awscdk, and the "beats awscdk outright" framing it
# fed into the spec's own arm prediction, has been corrected.
#
# NoOpUserData: verified directly at authoring time (real cdktn synth) that
# lib/aws/compute/user-data.js's UserData.render() -- every built-in
# subclass, including the plain LinuxUserData that
# MachineImage.genericLinux()'s own default (`UserData.forLinux()`, see
# GenericLinuxImage.getImage()) supplies unconditionally when no `userData`
# prop is given -- ALWAYS synthesizes a `data "cloudinit_config"`
# (hashicorp/cloudinit provider) resource. That provider is NOT part of
# this arm's offline provider mirror (arms/terraconstructs/environment/
# mirror-src/main.tf mirrors hashicorp/aws + hashicorp/archive only) --
# confirmed directly against `make falsifiability`'s own real sandbox run
# (2026-08-21) on an earlier draft of this file that registered
# CloudinitProvider instead: reward was 1.0 (every structural fact
# correct) but the gate itself still reported FAIL, with
# `mirror_detail: provider(s) required by this artifact are MISSING from
# the arm image's own offline mirror: registry.terraform.io/hashicorp/
# cloudinit@2.4.0 (mirror has: nothing)` -- i.e. cdktn synth succeeded
# (CloudinitProvider satisfies ITS OWN "matching provider construct"
# validation) but the subsequent real `terraform init` a trial's own
# static_tiers.sh always runs after synth (SCHEMA.md's own tf-plan-step
# note) cannot resolve the provider PLUGIN itself from this arm's offline
# mirror. Registering `@cdktn/provider-cloudinit`'s
# CloudinitProvider construct does NOT fix this (it only avoids cdktn
# synth's own "missing provider construct" validation, not the underlying
# missing MIRROR entry a real offline `terraform init` still needs) --
# widening the shared, non-scenario-specific mirror is out of this
# scenario's own authoring scope (SCHEMA.md's own generation-time
# boundary; a mirror change is a batch-wide, cross-scenario decision per
# docs/design/batch-a-greenfield-blueprints.md §0.3). The oracle-correct
# fix instead avoids the cloudinit-backed rendering path entirely: a
# minimal custom UserData subclass whose own render() returns a plain
# empty string, passed explicitly via GenericLinuxImageProps.userData
# (checked BEFORE the library's own UserData.forLinux() default -- see
# GenericLinuxImage.getImage()'s own `this.props.userData ?? UserData.
# forLinux()`). Neither this scenario's own prompt nor its oracle asks for
# any userData content, so an empty script is a genuinely correct answer,
# not a workaround-shaped one.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, Tags, compute } from "terraconstructs/lib/aws";

// See this file's own header comment ("NoOpUserData") for why this exists:
// every built-in UserData implementation renders through an offline-
// unmirrored Terraform provider (hashicorp/cloudinit). This scenario's own
// prompt never asks for instance bootstrap content, so an empty render()
// is a correct answer, not a stand-in for one.
class NoOpUserData extends compute.UserData {
  readonly content = "";
  readonly contentType = undefined;
  readonly filename = undefined;
  addCommands(): void {}
  addOnExitCommands(): void {}
  render(): string {
    return "";
  }
  addS3DownloadCommand(): string {
    return "";
  }
  addExecuteFileCommand(): void {}
}

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // Explicit availabilityZones: compute.Vpc's default AZ resolution
    // creates an unmockable `data "aws_availability_zones"` lookup
    // offline (this scenario's own header comment) -- literal AZs in this
    // arm's pinned region (us-east-1, arms/terraconstructs/environment/
    // app/main.ts) avoid it entirely.
    const vpc = new compute.Vpc(this, "WorkerVpc", {
      availabilityZones: ["us-east-1a", "us-east-1b"],
      natGateways: 0,
      subnetConfiguration: [
        {
          name: "Private",
          subnetType: compute.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    // No explicit launchTemplate: this library's AutoScalingGroup
    // unconditionally builds one internally as a child construct from
    // instanceType/machineImage (see this file's own header comment) --
    // unlike awscdk, an explicit LaunchTemplate construction step is not
    // needed to reach the volume half here.
    const fleet = new compute.autoscaling.AutoScalingGroup(this, "WorkerFleet", {
      vpc,
      vpcSubnets: { subnetType: compute.SubnetType.PRIVATE_ISOLATED },
      instanceType: new compute.InstanceType("t3.small"),
      machineImage: compute.MachineImage.genericLinux(
        { "us-east-1": "ami-0c55b159cbfafe1f0" },
        { userData: new NoOpUserData() },
      ),
      minCapacity: 2,
      maxCapacity: 6,
    });

    // ONE aspect call, scoped to the ASG construct, reaches the ASG's own
    // tag-propagation blocks AND the internally-created launch template's
    // instance+volume tag_specifications -- see this file's own header
    // comment for the source-verified mechanism.
    Tags.of(fleet).add("CostCenter", "platform-42");
    Tags.of(fleet).add("Environment", "prod");
  }
}
TS

bash tests/static_tiers.sh
