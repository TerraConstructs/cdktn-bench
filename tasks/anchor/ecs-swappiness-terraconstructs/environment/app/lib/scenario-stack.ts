// ECS EC2 task definition: tuned container memory swappiness
//
// Generated skeleton -- generator/gen.py, from specs/ecs-swappiness.yaml.
// This is YOUR file -- the App/provider bootstrap (imports this
// class and instantiates it) lives in ../main.ts; do not modify
// that file. Empty on purpose: the agent fills this in per the task
// instruction. Do not hand-edit this header; regenerate instead
// (`make gen SPEC=specs/ecs-swappiness.yaml`).
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // TODO(agent): see the task instruction for what to create here.
  }
}
