#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { ExampleStack } from "../lib/example-stack";

/**
 * cdktn-bench awscdk arm — workspace entrypoint.
 *
 * This is the starting scaffold copied into every generated task's agent
 * container (see ../../README.md). The generator (Slice C) overwrites
 * lib/ with the scenario-specific stack; this file and ExampleStack exist
 * so that:
 *   1. `preflight.sh` has a real one-construct app to synth offline, and
 *   2. an agent dropped into an unmodified workspace sees a working,
 *      idiomatic example rather than an empty directory.
 *
 * No `env: { account, region }` is set on purpose — synth-only oracle tiers
 * never need AWS credentials or environment lookups (`cdk synth --no-lookups`).
 */
const app = new cdk.App();

new ExampleStack(app, "ExampleStack", {
  description: "cdktn-bench awscdk arm placeholder stack (replaced by the generator).",
});
