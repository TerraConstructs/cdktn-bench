import { Construct } from "constructs";
import { AwsStack, AwsStackProps, compute } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const quoteService = new compute.LambdaFunction(this, "QuoteService", {
      functionName: "cdktn-bench-quote-service",
      runtime: compute.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        [
          "exports.handler = async () => ({",
          "  statusCode: 200,",
          "  body: JSON.stringify({ currency: process.env.QUOTE_CURRENCY }),",
          "});",
        ].join("\n"),
      ),
      environment: {
        QUOTE_CURRENCY: "USD",
      },
      publish: true,
    });

    new compute.Alias(this, "LiveAlias", {
      aliasName: "live",
      function: quoteService,
      version: quoteService.version,
    });
  }
}
