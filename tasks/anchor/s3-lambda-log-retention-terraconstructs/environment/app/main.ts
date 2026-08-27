// S3 upload triggers Lambda; log group retains 10 days
//
// Generated entrypoint -- generator/gen.py. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "s3-lambda-log-retention", {
  environmentName: "cdktn-bench",
  gridUUID: "s3-lambda-log-retention",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
