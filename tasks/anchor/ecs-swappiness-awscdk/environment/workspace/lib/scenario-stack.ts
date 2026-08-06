import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";

/**
 * ECS EC2 task definition: tuned container memory swappiness
 *
 * Generated skeleton -- generator/gen.py, from specs/ecs-swappiness.yaml.
 * Empty on purpose: the agent fills this in per the task
 * instruction. Do not hand-edit; regenerate instead
 * (`make gen SPEC=specs/ecs-swappiness.yaml`).
 */
export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // TODO(agent): see the task instruction for what to create here.
  }
}
