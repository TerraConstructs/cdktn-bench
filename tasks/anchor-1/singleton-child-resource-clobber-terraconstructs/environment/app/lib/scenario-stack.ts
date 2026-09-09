import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { Bucket } from "terraconstructs/lib/aws/storage";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new Bucket(this, "Reports", {
      bucketName: "cdktn-bench-reports-archive",
      forceDestroy: true,
      lifecycleRules: [
        {
          id: "expire-raw-logs",
          enabled: true,
          filter: [{ prefix: "logs/" }],
          expiration: [{ days: 30 }],
        },
      ],
    });
  }
}
