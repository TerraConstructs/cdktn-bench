import * as cdk from 'aws-cdk-lib';
import { EnvironmentProps } from './lib/shared';
import { AnchorStack } from './stacks/anchor_stack';
import { QARolesStack } from './stacks/qa_roles_stack';

export function createEnvironment(app: cdk.App, envId: string, props: EnvironmentProps): void {
    new QARolesStack(app, `${envId}-QARoles-us-east-1`, { env: { account: props.account, region: 'us-east-1' } });
    new AnchorStack(app, `${envId}-Anchor-us-east-1`, { env: { account: props.account, region: 'us-east-1' } });
}
