// Event processor whose logs are kept for 30 days and cleaned up with the stack
//
// Generated entrypoint -- generator/gen.py. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "event-processor", {
  environmentName: "cdktn-bench",
  gridUUID: "event-processor",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
