// Document archive bucket with versioning, KMS encryption, TLS-only access and no public access
//
// Generated entrypoint -- generator/gen.py. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "document-archive", {
  environmentName: "cdktn-bench",
  gridUUID: "document-archive",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
