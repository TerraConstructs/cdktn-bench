// Minimal terraconstructs preflight app.
//
// Purpose: prove that terraconstructs' AWSCDK-style L2 constructs synthesize
// to Terraform JSON fully offline (no terraform binary, no AWS credentials,
// no network access at synth time — @cdktn/provider-aws ships prebuilt
// provider bindings, so no `cdktn get`/`terraform init` is required to synth).
//
// Exercises the same constructs the s3-lambda-log-retention seed scenario
// needs: an S3 Bucket and a CloudWatch LogGroup with a typed `RetentionDays`
// enum (the same enum-based catch as aws-cdk-lib: ONE_WEEK=7, TWO_WEEKS=14,
// no literal "10" exists) — see arms/terraconstructs/README.md for the full
// per-scenario coverage verdict.
import { App } from "cdktn";
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, RetentionDays } from "terraconstructs/lib/aws";
import { Bucket } from "terraconstructs/lib/aws/storage";
import { LogGroup } from "terraconstructs/lib/aws/cloudwatch";

class PreflightStack extends AwsStack {
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

const app = new App();
new PreflightStack(app, "cdktn-bench-preflight", {
  environmentName: "preflight",
  gridUUID: "cdktn-bench-preflight",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
