// API Gateway REST API (live)
//
// Generated entrypoint -- generator/gen.py. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "hello-version-api", {
  environmentName: "cdktn-bench",
  gridUUID: "hello-version-api",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
