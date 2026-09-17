import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new storage.Repository(this, "ServiceImageRegistry", {
      repositoryName: "service-image-registry",
      imageScanOnPush: true,
      emptyOnDelete: true,
      lifecycleRules: [{ maxImageCount: 10 }],
    });
  }
}
