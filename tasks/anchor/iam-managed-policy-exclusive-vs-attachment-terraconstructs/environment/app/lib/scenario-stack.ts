// Two service roles that share the same managed policies
//
// Generated skeleton -- generator/gen.py.
// This is YOUR file -- the App/provider bootstrap (imports this
// class and instantiates it) lives in ../main.ts; do not modify
// that file. Empty on purpose: the agent fills this in per the task
// instruction. Do not hand-edit this header; regenerate instead
// (`make gen`).
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // TODO(agent): see the task instruction for what to create here.
  }
}
