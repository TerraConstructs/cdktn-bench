// Internal services network
//
// Generated entrypoint -- generator/gen.py. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "internal-services-network", {
  environmentName: "cdktn-bench",
  gridUUID: "internal-services-network",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
