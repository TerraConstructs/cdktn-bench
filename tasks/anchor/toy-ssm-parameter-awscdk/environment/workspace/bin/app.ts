#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { ScenarioStack } from "../lib/scenario-stack";

/**
 * Generated entrypoint -- generator/gen.py, from specs/toy-ssm-parameter.yaml.
 * Regenerate, do not hand-edit.
 *
 * No `env: { account, region }` on purpose -- synth-only oracle
 * tiers never need AWS credentials or environment lookups
 * (`cdk synth --no-lookups`).
 */
const app = new cdk.App();

new ScenarioStack(app, "ScenarioStack", {
  description: "Toy: SSM parameter + read-only IAM role",
});
