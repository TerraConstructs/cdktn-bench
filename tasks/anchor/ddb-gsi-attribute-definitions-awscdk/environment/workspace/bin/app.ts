#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { ScenarioStack } from "../lib/scenario-stack";

/**
 * Generated entrypoint -- generator/gen.py.
 * Regenerate, do not hand-edit.
 *
 * No `env: { account, region }` on purpose -- synth-only oracle
 * tiers never need AWS credentials or environment lookups
 * (`cdk synth --no-lookups`).
 *
 * Standard `new cdk.App()` (default synthesizer): live `cdk deploy`
 * uses the CDKToolkit bootstrap roles (`cdk-hnb659fds-*`, created by
 * deploy.sh's `cdk bootstrap`). The mutation agent runs as
 * `QALocalInvocationApplicationAdmin` (AdministratorAccess, DECISIONS.md
 * Amendment 24), which can assume those roles -- so this is the normal,
 * representative awscdk deploy path, deploying with the same broad
 * authority the hcl-raw arm's terraform gets (arm parity). CloudFormation
 * runs as the bootstrap cfn-exec-role, itself AdministratorAccess, so no
 * arm gets more authority than the other.
 */
const app = new cdk.App();

new ScenarioStack(app, "ScenarioStack", {
  description: "Orders table with a per-customer query index",
});
