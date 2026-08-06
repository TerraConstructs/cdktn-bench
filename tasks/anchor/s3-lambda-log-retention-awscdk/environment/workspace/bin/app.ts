#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { ScenarioStack } from "../lib/scenario-stack";

/**
 * Generated entrypoint -- generator/gen.py, from specs/s3-lambda-log-retention.yaml.
 * Regenerate, do not hand-edit.
 *
 * No `env: { account, region }` on purpose -- synth-only oracle
 * tiers never need AWS credentials or environment lookups
 * (`cdk synth --no-lookups`).
 */
const app = new cdk.App();

new ScenarioStack(app, "ScenarioStack", {
  description: "S3 upload triggers Lambda; log group retains 10 days",
});
