import * as cdk from 'aws-cdk-lib';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import { StackUtils } from '../lib/shared';

/**
 * AnchorStack — the near-empty scenario payload (build plan Phase 0,
 * mismatch M1). A single free-tier `AWS::SSM::Parameter` (String, no
 * KMS key, no advanced tier) is the only resource: enough for CDK to
 * bootstrap/deploy/destroy a real stack in a real account, at $0
 * marginal cost. No task in this benchmark reads this parameter — every
 * task's grading is offline (synth/plan + static oracles) inside the
 * agent's own container, per docs/iac-abstraction-aws-bench-plan.md
 * Phase 0.
 */
export class AnchorStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props: cdk.StackProps) {
        super(scope, id, props);

        const anchor = new ssm.StringParameter(this, 'AnchorParameter', {
            parameterName: `/cdktn-bench/${this.stackName}/anchor`,
            stringValue: 'cdktn-bench-anchor',
            description: 'Zero-cost anchor resource; satisfies aws-bench env init/setup/cleanup only.',
            tier: ssm.ParameterTier.STANDARD,
        });

        StackUtils.exportStack(this, 'AnchorParameterName', anchor.parameterName);
        StackUtils.exportStack(this, 'StackId', this.stackId, 'Name of the Stack');
    }
}
