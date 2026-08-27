// Auto Scaling worker fleet whose instances and volumes carry cost-allocation tags
//
// Generated entrypoint -- generator/gen.py. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "worker-fleet", {
  environmentName: "cdktn-bench",
  gridUUID: "worker-fleet",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
