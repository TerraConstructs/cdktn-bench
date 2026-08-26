import * as cdk from "aws-cdk-lib";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const accessLogs = new s3.Bucket(this, "AccessLogs", {
      bucketName: "cdktn-bench-application-storage-access-logs",
      accessControl: s3.BucketAccessControl.LOG_DELIVERY_WRITE,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const appData = new s3.Bucket(this, "AppData", {
      bucketName: "cdktn-bench-application-storage-app-data",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const accessLogsBucket = accessLogs.node.defaultChild as s3.CfnBucket;
    const appDataBucket = appData.node.defaultChild as s3.CfnBucket;

    appDataBucket.loggingConfiguration = {
      destinationBucketName: accessLogsBucket.ref,
      logFilePrefix: "app-data/",
    };
  }
}
