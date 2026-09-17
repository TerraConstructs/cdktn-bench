// Artifact bucket writable only by the pipeline identity that deploys it
//
// Generated entrypoint -- generator/gen.py. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "release-artifact-store", {
  environmentName: "cdktn-bench",
  gridUUID: "release-artifact-store",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
