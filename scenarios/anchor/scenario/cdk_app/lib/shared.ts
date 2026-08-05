import * as cdk from 'aws-cdk-lib';

export interface EnvironmentProps {
    readonly account: string;
}

// Copied verbatim from aws-bench-datasets scenarios' lib/shared.ts (every
// scenario's export must go through this so exportName follows the
// `${stackName}-${name}` convention the placeholder-resolution test expects
// — see docs/aws-bench-datasets-guide.md §6a).
export class StackUtils {
    static exportStack(stack: cdk.Stack, name: string, value: string, description?: string): cdk.CfnOutput {
        return new cdk.CfnOutput(stack, name, {
            value,
            exportName: `${stack.stackName}-${name}`,
            description,
        });
    }
}
