// arms/terraconstructs preflight — PreflightStack.
//
// Lives in lib/ (not main.ts) on purpose: this is the SAME file-layout
// split the Slice C generator uses for every scenario task —
// generator/gen.py::terraconstructs_stack_skeleton() writes the agent-owned
// resource file here (as lib/scenario-stack.ts, output_contract.entry_file)
// and terraconstructs_main_ts() writes the non-agent-owned App/provider
// bootstrap to ../main.ts — mirroring arms/awscdk's bin/app.ts /
// lib/example-stack.ts split. Keeping the arm's own preflight app in this
// same two-file shape means `make preflight` exercises the split for real,
// not just the generated tasks.
//
// Exercises the same constructs an S3-plus-log-retention seed scenario
// needs: an S3 Bucket and a CloudWatch LogGroup with a typed `RetentionDays`
// enum (the same enum-based catch as aws-cdk-lib: ONE_WEEK=7, TWO_WEEKS=14,
// no literal "10" exists) — see arms/terraconstructs/README.md for the full
// per-scenario coverage verdict.
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, RetentionDays } from "terraconstructs/lib/aws";
import { Bucket } from "terraconstructs/lib/aws/storage";
import { LogGroup } from "terraconstructs/lib/aws/cloudwatch";

export class PreflightStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const bucket = new Bucket(this, "PreflightBucket", {});

    new LogGroup(this, "PreflightLogGroup", {
      logGroupName: "/cdktn-bench/terraconstructs-preflight",
      retention: RetentionDays.TWO_WEEKS,
    });

    // touch the bucket so it isn't tree-shaken / flagged unused
    void bucket;
  }
}
