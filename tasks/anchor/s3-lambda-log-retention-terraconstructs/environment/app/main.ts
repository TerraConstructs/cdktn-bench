// S3 upload triggers Lambda; log group retains 10 days
//
// Generated -- generator/gen.py, from specs/s3-lambda-log-retention.yaml. App +
// provider bootstrap ONLY -- NOT the file you edit (see
// lib/scenario-stack.ts for that). Do not hand-edit; regenerate
// instead (`make gen SPEC=specs/s3-lambda-log-retention.yaml`).
import { App } from "cdktn";
import { ScenarioStack } from "./lib/scenario-stack";

const app = new App();
new ScenarioStack(app, "s3-lambda-log-retention", {
  environmentName: "cdktn-bench",
  gridUUID: "s3-lambda-log-retention",
  providerConfig: {
    region: "us-east-1",

    // Same skip_*/dummy-credential fixture as arms/hcl-raw's
    // provider.tf (see ../../README.md "What terraform plan
    // needs") -- gen.py's static_tiers.sh always runs a real
    // `terraform init && terraform plan` against this synthesized
    // stack (see build_static_tiers_sh's tf-plan step), so this arm
    // needs the same offline-plan fixture hcl_raw has, not just an
    // offline synth.
    accessKey: "AKIAIOSFODNN7EXAMPLE",
    secretKey: "dummy-secret-key-not-real",
    skipCredentialsValidation: true,
    skipRequestingAccountId: true,
    skipRegionValidation: true,
    skipMetadataApiCheck: "true",

    // AwsStack's `account` getter lazily creates an EXPLICIT
    // `data "aws_caller_identity"` the moment any construct
    // references it (most L2s do, for ARN formatting) --
    // `skipRequestingAccountId` above only suppresses the
    // provider's own IMPLICIT account lookup, not this data
    // source's real STS call. Point it at the loopback mock
    // static_tiers.sh's tf-plan step starts before `terraform
    // plan` (mock-sts.js, byte-copied to /app/project/mock-sts.js)
    // so the plan resolves offline. See DECISIONS.md
    // "terraconstructs offline `terraform plan` needs a mocked STS
    // endpoint". Do not remove this block -- an idiomatic L2
    // solution (e.g. a bare Bucket or Role construct) will fail
    // `terraform plan` with a 403 InvalidClientTokenId without it.
    // This file is NOT entry_file, so an agent fully rewriting
    // lib/scenario-stack.ts can never delete this block.
    endpoints: [{ sts: "http://127.0.0.1:17771" }],
  },
});
app.synth();
