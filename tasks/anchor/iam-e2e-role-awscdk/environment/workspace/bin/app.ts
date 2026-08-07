#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { ScenarioStack } from "../lib/scenario-stack";

/**
 * Generated entrypoint -- generator/gen.py, from specs/iam-e2e-role.yaml.
 * Regenerate, do not hand-edit.
 *
 * No `env: { account, region }` on purpose -- synth-only oracle
 * tiers never need AWS credentials or environment lookups
 * (`cdk synth --no-lookups`).
 */
const app = new cdk.App();

new ScenarioStack(app, "ScenarioStack", {
  description: "IAM E2E role derivation: author deployer + workload permissions against real AWS denials",
});
