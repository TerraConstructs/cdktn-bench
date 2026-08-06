// Minimal terraconstructs preflight app — App/provider bootstrap only.
//
// Purpose: prove that terraconstructs' AWSCDK-style L2 constructs synthesize
// to Terraform JSON fully offline (no terraform binary, no AWS credentials,
// no network access at synth time — @cdktn/provider-aws ships prebuilt
// provider bindings, so no `cdktn get`/`terraform init` is required to synth).
//
// This file is deliberately App/provider-bootstrap ONLY — the stack's
// resource logic lives in ./lib/scenario-stack.ts. This is the same
// two-file split the Slice C generator uses for every scenario task
// (generator/gen.py's terraconstructs_main_ts() / terraconstructs_stack_
// skeleton(), mirroring arms/awscdk's bin/app.ts / lib/example-stack.ts
// split) — see ../README.md "Generated-task workspace split".
import { App } from "cdktn";
import { PreflightStack } from "./lib/scenario-stack";

const app = new App();
new PreflightStack(app, "cdktn-bench-preflight", {
  environmentName: "preflight",
  gridUUID: "cdktn-bench-preflight",
  providerConfig: {
    region: "us-east-1",
  },
});
app.synth();
