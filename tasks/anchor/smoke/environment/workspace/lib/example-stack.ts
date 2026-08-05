import * as cdk from "aws-cdk-lib";
import { aws_s3 as s3 } from "aws-cdk-lib";
import { Construct } from "constructs";

/**
 * Minimal one-construct stack used by `preflight.sh` to prove the toolchain
 * (tsc -> cdk synth) works fully offline, with no AWS credentials and no
 * network access. Replaced by the generator (Slice C) with the
 * scenario-specific stack for real tasks.
 */
export class ExampleStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    new s3.Bucket(this, "ExampleBucket", {
      versioned: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });
  }
}
