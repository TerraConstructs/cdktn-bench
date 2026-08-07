// IAM E2E role derivation: author deployer + workload permissions against real AWS denials
//
// Generated skeleton -- generator/gen.py, from specs/iam-e2e-role.yaml.
// This is YOUR file -- the App/provider bootstrap (imports this
// class and instantiates it) lives in ../main.ts; do not modify
// that file. Empty on purpose: the agent fills this in per the task
// instruction. Do not hand-edit this header; regenerate instead
// (`make gen SPEC=specs/iam-e2e-role.yaml`).
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // TODO(agent): see the task instruction for what to create here.
  }
}
