// Toy: SSM parameter + read-only IAM role
//
// Generated entrypoint -- generator/gen.py. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "toy-ssm-parameter", {
  environmentName: "cdktn-bench",
  gridUUID: "toy-ssm-parameter",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
