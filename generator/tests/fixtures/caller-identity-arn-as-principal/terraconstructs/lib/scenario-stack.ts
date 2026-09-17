import { DataAwsCallerIdentity } from "@cdktn/provider-aws/lib/data-aws-caller-identity";
import { DataAwsIamSessionContext } from "@cdktn/provider-aws/lib/data-aws-iam-session-context";
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, iam, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const caller = new DataAwsCallerIdentity(this, "Deployer", {});
    // The deploying credentials are an STS session, not an identity IAM can
    // name in a policy; this maps that session back to the role that issued it.
    const session = new DataAwsIamSessionContext(this, "DeployerSession", {
      arn: caller.arn,
    });

    const bucket = new storage.Bucket(this, "ReleaseArtifacts", {});

    bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "PipelineOnly",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ArnPrincipal(session.issuerArn)],
        actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        resources: [bucket.bucketArn, bucket.arnForObjects("*")],
      }),
    );
  }
}
