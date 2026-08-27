// API Gateway REST API from an OpenAPI spec, with per-route Lambda integrations
//
// Generated entrypoint -- generator/gen.py. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "apigw-openapi", {
  environmentName: "cdktn-bench",
  gridUUID: "apigw-openapi",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
