import {
  s3BucketAcl,
  s3BucketLogging,
  s3BucketOwnershipControls,
} from "@cdktn/provider-aws";
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { Bucket } from "terraconstructs/lib/aws/storage";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const accessLogs = new Bucket(this, "AccessLogs", {
      bucketName: "cdktn-bench-application-storage-access-logs",
      forceDestroy: true,
    });

    const accessLogsOwnership =
      new s3BucketOwnershipControls.S3BucketOwnershipControls(
        this,
        "AccessLogsOwnership",
        {
          bucket: accessLogs.bucketName,
          rule: { objectOwnership: "ObjectWriter" },
        },
      );

    const accessLogsAcl = new s3BucketAcl.S3BucketAcl(
      this,
      "AccessLogsAcl",
      {
        bucket: accessLogs.bucketName,
        acl: "log-delivery-write",
        dependsOn: [accessLogsOwnership],
      },
    );

    const appData = new Bucket(this, "AppData", {
      bucketName: "cdktn-bench-application-storage-app-data",
      forceDestroy: true,
    });

    new s3BucketLogging.S3BucketLoggingA(this, "AppDataLogging", {
      bucket: appData.bucketName,
      targetBucket: accessLogs.bucketName,
      targetPrefix: "app-data/",
      dependsOn: [accessLogsAcl],
    });
  }
}
