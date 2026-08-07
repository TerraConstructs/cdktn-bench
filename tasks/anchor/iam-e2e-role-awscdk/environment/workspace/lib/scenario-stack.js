"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.ScenarioStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const iam = __importStar(require("aws-cdk-lib/aws-iam"));
/**
 * REFERENCE SOLUTION (used by solution/solve.sh) -- IAM E2E role
 * derivation: author deployer + workload permissions against real AWS
 * denials.
 *
 * Mirrors ../../iam-e2e-role-hcl-raw/environment/workspace/main.tf's own
 * action/resource-scoping decisions exactly (the account-id-placeholder
 * workaround that arm needs does NOT apply here -- CDK resolves
 * `cdk.Aws.ACCOUNT_ID` via a CloudFormation pseudo-parameter, which needs
 * no data source / no real AWS call at synth time, unlike Terraform's
 * `data "aws_caller_identity"`; see the hcl_raw reference's own comment
 * for that arm-specific gap).
 */
class ScenarioStack extends cdk.Stack {
    constructor(scope, id, props) {
        super(scope, id, props);
        const accountId = cdk.Aws.ACCOUNT_ID;
        const externalId = "iam-e2e-role-trial-2026";
        const rolePath = "/cdktn-bench-task/";
        const instanceProfileArn = `arn:aws:iam::${accountId}:instance-profile/cdktn-bench-iam-e2e-role-workload-profile`;
        const ssmAppParamArnGlob = `arn:aws:ssm:us-east-1:${accountId}:parameter/cdktn-bench-iam-e2e-role/app/*`;
        const s3ScratchArn = "arn:aws:s3:::cdktn-bench-iam-e2e-*-scratch";
        const s3ScratchObjectsArn = "arn:aws:s3:::cdktn-bench-iam-e2e-*-scratch/*";
        const workloadRoleArn = `arn:aws:iam::${accountId}:role${rolePath}iam-e2e-role-workload`;
        // --- DEPLOYER role ---------------------------------------------------
        const deployerRole = new iam.Role(this, "DeployerRole", {
            roleName: "iam-e2e-role-deployer",
            path: rolePath,
            assumedBy: new iam.AccountPrincipal(accountId).withConditions({
                StringEquals: { "sts:ExternalId": externalId },
            }),
        });
        deployerRole.attachInlinePolicy(new iam.Policy(this, "DeployerPolicy", {
            statements: [
                new iam.PolicyStatement({
                    sid: "ReadOnlyDiscovery",
                    actions: [
                        "ec2:Describe*",
                        "ec2:GetSecurityGroupsForVpc",
                        "ec2:DescribeVolumeStatus",
                        "ssm:DescribeParameters",
                        "sts:GetCallerIdentity",
                    ],
                    resources: ["*"],
                }),
                new iam.PolicyStatement({
                    sid: "SsmRead",
                    actions: ["ssm:GetParameter", "ssm:GetParameters"],
                    resources: [ssmAppParamArnGlob],
                }),
                new iam.PolicyStatement({
                    sid: "InstanceProfileLifecycle",
                    actions: [
                        "iam:CreateInstanceProfile",
                        "iam:DeleteInstanceProfile",
                        "iam:GetInstanceProfile",
                        "iam:AddRoleToInstanceProfile",
                        "iam:RemoveRoleFromInstanceProfile",
                        "iam:TagInstanceProfile",
                        "iam:UntagInstanceProfile",
                        "iam:ListInstanceProfilesForRole",
                        "iam:GetRole",
                        "iam:ListRoleTags",
                    ],
                    resources: [instanceProfileArn, workloadRoleArn],
                }),
                new iam.PolicyStatement({
                    sid: "AssumeWorkloadForTesting",
                    actions: ["sts:AssumeRole"],
                    resources: [workloadRoleArn],
                }),
                new iam.PolicyStatement({
                    sid: "Ec2Write",
                    actions: [
                        "ec2:CreateSecurityGroup",
                        "ec2:DeleteSecurityGroup",
                        "ec2:AuthorizeSecurityGroupEgress",
                        "ec2:RevokeSecurityGroupEgress",
                        "ec2:CreateTags",
                        "ec2:DeleteTags",
                        "ec2:CreateVolume",
                        "ec2:DeleteVolume",
                    ],
                    resources: ["*"],
                }),
                new iam.PolicyStatement({
                    sid: "KmsUseForEbs",
                    actions: [
                        "kms:DescribeKey",
                        "kms:Decrypt",
                        "kms:GenerateDataKey",
                        "kms:GenerateDataKeyWithoutPlaintext",
                        "kms:CreateGrant",
                    ],
                    resources: ["*"],
                    conditions: { StringEquals: { "kms:ViaService": "ec2.us-east-1.amazonaws.com" } },
                }),
                new iam.PolicyStatement({
                    sid: "S3Scratch",
                    actions: [
                        "s3:CreateBucket",
                        "s3:DeleteBucket",
                        "s3:ListBucket",
                        "s3:GetBucket*",
                        "s3:PutBucket*",
                        "s3:DeleteBucketPolicy",
                        "s3:ListTagsForResource",
                        "s3:GetAccelerateConfiguration",
                        "s3:GetLifecycleConfiguration",
                        "s3:GetReplicationConfiguration",
                        "s3:GetEncryptionConfiguration",
                        "s3:PutEncryptionConfiguration",
                    ],
                    resources: [s3ScratchArn, s3ScratchObjectsArn],
                }),
            ],
        }));
        // --- WORKLOAD role -----------------------------------------------------
        // Never given any permission by module/ itself -- every grant below is
        // authored here, by hand, on THIS arm just like on hcl_raw (not via a
        // grantXxx() call on an imported construct -- see this scenario's own
        // provenance notes on why the v1 reference solution is symmetric across
        // arms rather than exercising the grantXxx-derivation contrast directly
        // in this reference; a future revision could redo this half with
        // StringParameter.fromSecureStringParameterAttributes(...).grantRead()
        // + Key.fromKeyArn(...).grantDecrypt() to demonstrate the construct-arm
        // win on THIS specific role for real).
        const workloadRole = new iam.Role(this, "WorkloadRole", {
            roleName: "iam-e2e-role-workload",
            path: rolePath,
            assumedBy: new iam.CompositePrincipal(new iam.ServicePrincipal("ec2.amazonaws.com"), new iam.AccountPrincipal(accountId).withConditions({
                StringEquals: { "sts:ExternalId": externalId },
            })),
        });
        workloadRole.attachInlinePolicy(new iam.Policy(this, "WorkloadPolicy", {
            statements: [
                new iam.PolicyStatement({
                    sid: "ReadAppParameters",
                    actions: [
                        "ssm:GetParameter",
                        "ssm:GetParameters",
                        "ssm:GetParametersByPath",
                        "ssm:DescribeParameters",
                    ],
                    resources: [ssmAppParamArnGlob],
                }),
                new iam.PolicyStatement({
                    sid: "DecryptSecureStringViaSsm",
                    actions: ["kms:Decrypt", "kms:DescribeKey"],
                    resources: ["*"],
                    conditions: { StringEquals: { "kms:ViaService": "ssm.us-east-1.amazonaws.com" } },
                }),
                new iam.PolicyStatement({
                    sid: "SelfDiscovery",
                    actions: ["ec2:DescribeVolumes", "ec2:DescribeInstances"],
                    resources: ["*"],
                }),
            ],
        }));
        new cdk.CfnOutput(this, "DeployerRoleArn", { value: deployerRole.roleArn });
        new cdk.CfnOutput(this, "WorkloadRoleArn", { value: workloadRole.roleArn });
        new cdk.CfnOutput(this, "ExternalId", { value: externalId });
    }
}
exports.ScenarioStack = ScenarioStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoic2NlbmFyaW8tc3RhY2suanMiLCJzb3VyY2VSb290IjoiIiwic291cmNlcyI6WyJzY2VuYXJpby1zdGFjay50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7QUFBQSxNQUFZLEdBQUcsd0NBQW9CO0FBQ25DLE1BQVksR0FBRyxnREFBNEI7QUFHM0M7Ozs7Ozs7Ozs7OztHQVlHO0FBQ0gsbUJBQTJCLFNBQVEsR0FBRyxDQUFDLEtBQUs7SUFDMUMsWUFBWSxLQUFnQixFQUFFLEVBQVUsRUFBRSxLQUFzQjtRQUM5RCxLQUFLLENBQUMsS0FBSyxFQUFFLEVBQUUsRUFBRSxLQUFLLENBQUMsQ0FBQztRQUV4QixNQUFNLFNBQVMsR0FBRyxHQUFHLENBQUMsR0FBRyxDQUFDLFVBQVUsQ0FBQztRQUNyQyxNQUFNLFVBQVUsR0FBRyx5QkFBeUIsQ0FBQztRQUM3QyxNQUFNLFFBQVEsR0FBRyxvQkFBb0IsQ0FBQztRQUN0QyxNQUFNLGtCQUFrQixHQUFHLGdCQUFnQixTQUFTLDZEQUE2RCxDQUFDO1FBQ2xILE1BQU0sa0JBQWtCLEdBQUcseUJBQXlCLFNBQVMsMkNBQTJDLENBQUM7UUFDekcsTUFBTSxZQUFZLEdBQUcsNENBQTRDLENBQUM7UUFDbEUsTUFBTSxtQkFBbUIsR0FBRyw4Q0FBOEMsQ0FBQztRQUMzRSxNQUFNLGVBQWUsR0FBRyxnQkFBZ0IsU0FBUyxRQUFRLFFBQVEsdUJBQXVCLENBQUM7UUFFekYsd0VBQXdFO1FBQ3hFLE1BQU0sWUFBWSxHQUFHLElBQUksR0FBRyxDQUFDLElBQUksQ0FBQyxJQUFJLEVBQUUsY0FBYyxFQUFFO1lBQ3RELFFBQVEsRUFBRSx1QkFBdUI7WUFDakMsSUFBSSxFQUFFLFFBQVE7WUFDZCxTQUFTLEVBQUUsSUFBSSxHQUFHLENBQUMsZ0JBQWdCLENBQUMsU0FBUyxDQUFDLENBQUMsY0FBYyxDQUFDO2dCQUM1RCxZQUFZLEVBQUUsRUFBRSxnQkFBZ0IsRUFBRSxVQUFVLEVB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LENBQUMsR0FBRyxDQUFDO2lCQUNqQixDQUFDO2FBQ0g7U0FDRixDQUFDLENBQ0gsQ0FBQztRQUVGLElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsaUJBQWlCLEVBQUUsRUFBRSxLQUFLLEVBQUUsWUFBWSxDQUFDLE9BQU8sRUFBRSxDQUFDLENBQUM7UUFDNUUsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxpQkFBaUIsRUFBRSxFQUFFLEtBQUssRUFBRSxZQUFZLENBQUMsT0FBTyxFQUFFLENBQUMsQ0FBQztRQUM1RSxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLFlBQVksRUFBRSxFQUFFLEtBQUssRUFBRSxVQUFVLEVBQUUsQ0FBQyxDQUFDO0lBQy9ELENBQUM7Q0FDRiIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tIFwiYXdzLWNkay1saWJcIjtcbmltcG9ydCAqIGFzIGlhbSBmcm9tIFwiYXdzLWNkay1saWIvYXdzLWlhbVwiO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSBcImNvbnN0cnVjdHNcIjtcblxuLyoqXG4gKiBSRUZFUkVOQ0UgU09MVVRJT04gKHVzZWQgYnkgc29sdXRpb24vc29sdmUuc2gpIC0tIElBTSBFMkUgcm9sZVxuICogZGVyaXZhdGlvbjogYXV0aG9yIGRlcGxveWVyICsgd29ya2xvYWQgcGVybWlzc2lvbnMgYWdhaW5zdCByZWFsIEFXU1xuICogZGVuaWFscy5cbiAqXG4gKiBNaXJyb3JzIC4uLy4uL2lhbS1lMmUtcm9sZS1oY2wtcmF3L2Vudmlyb25tZW50L3dvcmtzcGFjZS9tYWluLnRmJ3Mgb3duXG4gKiBhY3Rpb24vcmVzb3VyY2Utc2NvcGluZyBkZWNpc2lvbnMgZXhhY3RseSAodGhlIGFjY291bnQtaWQtcGxhY2Vob2xkZXJcbiAqIHdvcmthcm91bmQgdGhhdCBhcm0gbmVlZHMgZG9lcyBOT1QgYXBwbHkgaGVyZSAtLSBDREsgcmVzb2x2ZXNcbiAqIGBjZGsuQXdzLkFDQ09VTlRfSURgIHZpYSBhIENsb3VkRm9ybWF0aW9uIHBzZXVkby1wYXJhbWV0ZXIsIHdoaWNoIG5lZWRzXG4gKiBubyBkYXRhIHNvdXJjZSAvIG5vIHJlYWwgQVdTIGNhbGwgYXQgc3ludGggdGltZSwgdW5saWtlIFRlcnJhZm9ybSdzXG4gKiBgZGF0YSBcImF3c19jYWxsZXJfaWRlbnRpdHlcImA7IHNlZSB0aGUgaGNsX3JhdyByZWZlcmVuY2UncyBvd24gY29tbWVudFxuICogZm9yIHRoYXQgYXJtLXNwZWNpZmljIGdhcCkuXG4gKi9cbmV4cG9ydCBjbGFzcyBTY2VuYXJpb1N0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM/OiBjZGsuU3RhY2tQcm9wcykge1xuICAgIHN1cGVyKHNjb3BlLCBpZCwgcHJvcHMpO1xuXG4gICAgY29uc3QgYWNjb3VudElkID0gY2RrLkF3cy5BQ0NPVU5UX0lEO1xuICAgIGNvbnN0IGV4dGVybmFsSWQgPSBcImlhbS1lMmUtcm9sZS10cmlhbC0yMDI2XCI7XG4gICAgY29uc3Qgcm9sZVBhdGggPSBcIi9jZGt0bi1iZW5jaC10YXNrL1wiO1xuICAgIGNvbnN0IGluc3RhbmNlUHJvZmlsZUFybiA9IGBhcm46YXdzOmlhbTo6JHthY2NvdW50SWR9Omluc3RhbmNlLXByb2ZpbGUvY2RrdG4tYmVuY2gtaWFtLWUyZS1yb2xlLXdvcmtsb2FkLXByb2ZpbGVgO1xuICAgIGNvbnN0IHNzbUFwcFBhcmFtQXJuR2xvYiA9IGBhcm46YXdzOnNzbTp1cy1lYXN0LTE6JHthY2NvdW50SWR9OnBhcmFtZXRlci9jZGt0bi1iZW5jaC1pYW0tZTJlLXJvbGUvYXBwLypgO1xuICAgIGNvbnN0IHMzU2NyYXRjaEFybiA9IFwiYXJuOmF3czpzMzo6OmNka3RuLWJlbmNoLWlhbS1lMmUtKi1zY3JhdGNoXCI7XG4gICAgY29uc3QgczNTY3JhdGNoT2JqZWN0c0FybiA9IFwiYXJuOmF3czpzMzo6OmNka3RuLWJlbmNoLWlhbS1lMmUtKi1zY3JhdGNoLypcIjtcbiAgICBjb25zdCB3b3JrbG9hZFJvbGVBcm4gPSBgYXJuOmF3czppYW06OiR7YWNjb3VudElkfTpyb2xlJHtyb2xlUGF0aH1pYW0tZTJlLXJvbGUtd29ya2xvYWRgO1xuXG4gICAgLy8gLS0tIERFUExPWUVSIHJvbGUgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tXG4gICAgY29uc3QgZGVwbG95ZXJSb2xlID0gbmV3IGlhbS5Sb2xlKHRoaXMsIFwiRGVwbG95ZXJSb2xlXCIsIHtcbiAgICAgIHJvbGVOYW1lOiBcImlhbS1lMmUtcm9sZS1kZXBsb3llclwiLFxuICAgICAgcGF0aDogcm9sZVBhdGgsXG4gICAgICBhc3N1bWVkQnk6IG5ldyBpYW0uQWNjb3VudFByaW5jaXBhbChhY2NvdW50SWQpLndpdGhDb25kaXRpb25zKHtcbiAgICAgICAgU3RyaW5nRXF1YWxzOiB7IFwic3RzOkV4dGVybmFsSWRcIjogZXh0ZXJuYWxJZCB9LFxuICAgICAgfSksXG4gICAgfSk7XG5cbiAgICBkZXBsb3llclJvbGUuYXR0YWNoSW5saW5lUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3kodGhpcywgXCJEZXBsb3llclBvbGljeVwiLCB7XG4gICAgICAgIHN0YXRlbWVudHM6IFtcbiAgICAgICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgICAgICBzaWQ6IFwiUmVhZE9ubHlEaXNjb3ZlcnlcIixcbiAgICAgICAgICAgIGFjdGlvbnM6IFtcbiAgICAgICAgICAgICAgXCJlYzI6RGVzY3JpYmUqXCIsXG4gICAgICAgICAgICAgIFwiZWMyOkdldFNlY3VyaXR5R3JvdXBzRm9yVnBjXCIsXG4gICAgICAgICAgICAgIFwiZWMyOkRlc2NyaWJlVm9sdW1lU3RhdHVzXCIsXG4gICAgICAgICAgICAgIFwic3NtOkRlc2NyaWJlUGFyYW1ldGVyc1wiLFxuICAgICAgICAgICAgICBcInN0czpHZXRDYWxsZXJJZGVudGl0eVwiLFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICAgIHJlc291cmNlczogW1wiKlwiXSxcbiAgICAgICAgICB9KSxcbiAgICAgICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgICAgICBzaWQ6IFwiU3NtUmVhZFwiLFxuICAgICAgICAgICAgYWN0aW9uczogW1wic3NtOkdldFBhcmFtZXRlclwiLCBcInNzbTpHZXRQYXJhbWV0ZXJzXCJdLFxuICAgICAgICAgICAgcmVzb3VyY2VzOiBbc3NtQXBwUGFyYW1Bcm5HbG9iXSxcbiAgICAgICAgICB9KSxcbiAgICAgICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgICAgICBzaWQ6IFwiSW5zdGFuY2VQcm9maWxlTGlmZWN5Y2xlXCIsXG4gICAgICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgICAgIFwiaWFtOkNyZWF0ZUluc3RhbmNlUHJvZmlsZVwiLFxuICAgICAgICAgICAgICBcImlhbTpEZWxldGVJbnN0YW5jZVByb2ZpbGVcIixcbiAgICAgICAgICAgICAgXCJpYW06R2V0SW5zdGFuY2VQcm9maWxlXCIsXG4gICAgICAgICAgICAgIFwiaWFtOkFkZFJvbGVUb0luc3RhbmNlUHJvZmlsZVwiLFxuICAgICAgICAgICAgICBcImlhbTpSZW1vdmVSb2xlRnJvbUluc3RhbmNlUHJvZmlsZVwiLFxuICAgICAgICAgICAgICBcImlhbTpUYWdJbnN0YW5jZVByb2ZpbGVcIixcbiAgICAgICAgICAgICAgXCJpYW06VW50YWdJbnN0YW5jZVByb2ZpbGVcIixcbiAgICAgICAgICAgICAgXCJpYW06TGlzdEluc3RhbmNlUHJvZmlsZXNGb3JSb2xlXCIsXG4gICAgICAgICAgICAgIFwiaWFtOkdldFJvbGVcIixcbiAgICAgICAgICAgICAgXCJpYW06TGlzdFJvbGVUYWdzXCIsXG4gICAgICAgICAgICBdLFxuICAgICAgICAgICAgcmVzb3VyY2VzOiBbaW5zdGFuY2VQcm9maWxlQXJuLCB3b3JrbG9hZFJvbGVBcm5dLFxuICAgICAgICAgIH0pLFxuICAgICAgICAgIG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgICAgICAgIHNpZDogXCJBc3N1bWVXb3JrbG9hZEZvclRlc3RpbmdcIixcbiAgICAgICAgICAgIGFjdGlvbnM6IFtcInN0czpBc3N1bWVSb2xlXCJdLFxuICAgICAgICAgICAgcmVzb3VyY2VzOiBbd29ya2xvYWRSb2xlQXJuXSxcbiAgICAgICAgICB9KSxcbiAgICAgICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgICAgICBzaWQ6IFwiRWMyV3JpdGVcIixcbiAgICAgICAgICAgIGFjdGlvbnM6IFtcbiAgICAgICAgICAgICAgXCJlYzI6Q3JlYXRlU2VjdXJpdHlHcm91cFwiLFxuICAgICAgICAgICAgICBcImVjMjpEZWxldGVTZWN1cml0eUdyb3VwXCIsXG4gICAgICAgICAgICAgIFwiZWMyOkF1dGhvcml6ZVNlY3VyaXR5R3JvdXBFZ3Jlc3NcIixcbiAgICAgICAgICAgICAgXCJlYzI6UmV2b2tlU2VjdXJpdHlHcm91cEVncmVzc1wiLFxuICAgICAgICAgICAgICBcImVjMjpDcmVhdGVUYWdzXCIsXG4gICAgICAgICAgICAgIFwiZWMyOkRlbGV0ZVRhZ3NcIixcbiAgICAgICAgICAgICAgXCJlYzI6Q3JlYXRlVm9sdW1lXCIsXG4gICAgICAgICAgICAgIFwiZWMyOkRlbGV0ZVZvbHVtZVwiLFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICAgIHJlc291cmNlczogW1wiKlwiXSxcbiAgICAgICAgICB9KSxcbiAgICAgICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgICAgICBzaWQ6IFwiS21zVXNlRm9yRWJzXCIsXG4gICAgICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgICAgIFwia21zOkRlc2NyaWJlS2V5XCIsXG4gICAgICAgICAgICAgIFwia21zOkRlY3J5cHRcIixcbiAgICAgICAgICAgICAgXCJrbXM6R2VuZXJhdGVEYXRhS2V5XCIsXG4gICAgICAgICAgICAgIFwia21zOkdlbmVyYXRlRGF0YUtleVdpdGhvdXRQbGFpbnRleHRcIixcbiAgICAgICAgICAgICAgXCJrbXM6Q3JlYXRlR3JhbnRcIixcbiAgICAgICAgICAgIF0sXG4gICAgICAgICAgICByZXNvdXJjZXM6IFtcIipcIl0sXG4gICAgICAgICAgICBjb25kaXRpb25zOiB7IFN0cmluZ0VxdWFsczogeyBcImttczpWaWFTZXJ2aWNlXCI6IFwiZWMyLnVzLWVhc3QtMS5hbWF6b25hd3MuY29tXCIgfSB9LFxuICAgICAgICAgIH0pLFxuICAgICAgICAgIG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgICAgICAgIHNpZDogXCJTM1NjcmF0Y2hcIixcbiAgICAgICAgICAgIGFjdGlvbnM6IFtcbiAgICAgICAgICAgICAgXCJzMzpDcmVhdGVCdWNrZXRcIixcbiAgICAgICAgICAgICAgXCJzMzpEZWxldGVCdWNrZXRcIixcbiAgICAgICAgICAgICAgXCJzMzpMaXN0QnVja2V0XCIsXG4gICAgICAgICAgICAgIFwiczM6R2V0QnVja2V0KlwiLFxuICAgICAgICAgICAgICBcInMzOlB1dEJ1Y2tldCpcIixcbiAgICAgICAgICAgICAgXCJzMzpEZWxldGVCdWNrZXRQb2xpY3lcIixcbiAgICAgICAgICAgICAgXCJzMzpMaXN0VGFnc0ZvclJlc291cmNlXCIsXG4gICAgICAgICAgICAgIFwiczM6R2V0QWNjZWxlcmF0ZUNvbmZpZ3VyYXRpb25cIixcbiAgICAgICAgICAgICAgXCJzMzpHZXRMaWZlY3ljbGVDb25maWd1cmF0aW9uXCIsXG4gICAgICAgICAgICAgIFwiczM6R2V0UmVwbGljYXRpb25Db25maWd1cmF0aW9uXCIsXG4gICAgICAgICAgICAgIFwiczM6R2V0RW5jcnlwdGlvbkNvbmZpZ3VyYXRpb25cIixcbiAgICAgICAgICAgICAgXCJzMzpQdXRFbmNyeXB0aW9uQ29uZmlndXJhdGlvblwiLFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICAgIHJlc291cmNlczogW3MzU2NyYXRjaEFybiwgczNTY3JhdGNoT2JqZWN0c0Fybl0sXG4gICAgICAgICAgfSksXG4gICAgICAgIF0sXG4gICAgICB9KSxcbiAgICApO1xuXG4gICAgLy8gLS0tIFdPUktMT0FEIHJvbGUgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS1cbiAgICAvLyBOZXZlciBnaXZlbiBhbnkgcGVybWlzc2lvbiBieSBtb2R1bGUvIGl0c2VsZiAtLSBldmVyeSBncmFudCBiZWxvdyBpc1xuICAgIC8vIGF1dGhvcmVkIGhlcmUsIGJ5IGhhbmQsIG9uIFRISVMgYXJtIGp1c3QgbGlrZSBvbiBoY2xfcmF3IChub3QgdmlhIGFcbiAgICAvLyBncmFudFh4eCgpIGNhbGwgb24gYW4gaW1wb3J0ZWQgY29uc3RydWN0IC0tIHNlZSB0aGlzIHNjZW5hcmlvJ3Mgb3duXG4gICAgLy8gcHJvdmVuYW5jZSBub3RlcyBvbiB3aHkgdGhlIHYxIHJlZmVyZW5jZSBzb2x1dGlvbiBpcyBzeW1tZXRyaWMgYWNyb3NzXG4gICAgLy8gYXJtcyByYXRoZXIgdGhhbiBleGVyY2lzaW5nIHRoZSBncmFudFh4eC1kZXJpdmF0aW9uIGNvbnRyYXN0IGRpcmVjdGx5XG4gICAgLy8gaW4gdGhpcyByZWZlcmVuY2U7IGEgZnV0dXJlIHJldmlzaW9uIGNvdWxkIHJlZG8gdGhpcyBoYWxmIHdpdGhcbiAgICAvLyBTdHJpbmdQYXJhbWV0ZXIuZnJvbVNlY3VyZVN0cmluZ1BhcmFtZXRlckF0dHJpYnV0ZXMoLi4uKS5ncmFudFJlYWQoKVxuICAgIC8vICsgS2V5LmZyb21LZXlBcm4oLi4uKS5ncmFudERlY3J5cHQoKSB0byBkZW1vbnN0cmF0ZSB0aGUgY29uc3RydWN0LWFybVxuICAgIC8vIHdpbiBvbiBUSElTIHNwZWNpZmljIHJvbGUgZm9yIHJlYWwpLlxuICAgIGNvbnN0IHdvcmtsb2FkUm9sZSA9IG5ldyBpYW0uUm9sZSh0aGlzLCBcIldvcmtsb2FkUm9sZVwiLCB7XG4gICAgICByb2xlTmFtZTogXCJpYW0tZTJlLXJvbGUtd29ya2xvYWRcIixcbiAgICAgIHBhdGg6IHJvbGVQYXRoLFxuICAgICAgYXNzdW1lZEJ5OiBuZXcgaWFtLkNvbXBvc2l0ZVByaW5jaXBhbChcbiAgICAgICAgbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKFwiZWMyLmFtYXpvbmF3cy5jb21cIiksXG4gICAgICAgIG5ldyBpYW0uQWNjb3VudFByaW5jaXBhbChhY2NvdW50SWQpLndpdGhDb25kaXRpb25zKHtcbiAgICAgICAgICBTdHJpbmdFcXVhbHM6IHsgXCJzdHM6RXh0ZXJuYWxJZFwiOiBleHRlcm5hbElkIH0sXG4gICAgICAgIH0pLFxuICAgICAgKSxcbiAgICB9KTtcblxuICAgIHdvcmtsb2FkUm9sZS5hdHRhY2hJbmxpbmVQb2xpY3koXG4gICAgICBuZXcgaWFtLlBvbGljeSh0aGlzLCBcIldvcmtsb2FkUG9saWN5XCIsIHtcbiAgICAgICAgc3RhdGVtZW50czogW1xuICAgICAgICAgIG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgICAgICAgIHNpZDogXCJSZWFkQXBwUGFyYW1ldGVyc1wiLFxuICAgICAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICAgICBcInNzbTpHZXRQYXJhbWV0ZXJcIixcbiAgICAgICAgICAgICAgXCJzc206R2V0UGFyYW1ldGVyc1wiLFxuICAgICAgICAgICAgICBcInNzbTpHZXRQYXJhbWV0ZXJzQnlQYXRoXCIsXG4gICAgICAgICAgICAgIFwic3NtOkRlc2NyaWJlUGFyYW1ldGVyc1wiLFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICAgIHJlc291cmNlczogW3NzbUFwcFBhcmFtQXJuR2xvYl0sXG4gICAgICAgICAgfSksXG4gICAgICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICAgICAgc2lkOiBcIkRlY3J5cHRTZWN1cmVTdHJpbmdWaWFTc21cIixcbiAgICAgICAgICAgIGFjdGlvbnM6IFtcImttczpEZWNyeXB0XCIsIFwia21zOkRlc2NyaWJlS2V5XCJdLFxuICAgICAgICAgICAgcmVzb3VyY2VzOiBbXCIqXCJdLFxuICAgICAgICAgICAgY29uZGl0aW9uczogeyBTdHJpbmdFcXVhbHM6IHsgXCJrbXM6VmlhU2VydmljZVwiOiBcInNzbS51cy1lYXN0LTEuYW1hem9uYXdzLmNvbVwiIH0gfSxcbiAgICAgICAgICB9KSxcbiAgICAgICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgICAgICBzaWQ6IFwiU2VsZkRpc2NvdmVyeVwiLFxuICAgICAgICAgICAgYWN0aW9uczogW1wiZWMyOkRlc2NyaWJlVm9sdW1lc1wiLCBcImVjMjpEZXNjcmliZUluc3RhbmNlc1wiXSxcbiAgICAgICAgICAgIHJlc291cmNlczogW1wiKlwiXSxcbiAgICAgICAgICB9KSxcbiAgICAgICAgXSxcbiAgICAgIH0pLFxuICAgICk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCBcIkRlcGxveWVyUm9sZUFyblwiLCB7IHZhbHVlOiBkZXBsb3llclJvbGUucm9sZUFybiB9KTtcbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCBcIldvcmtsb2FkUm9sZUFyblwiLCB7IHZhbHVlOiB3b3JrbG9hZFJvbGUucm9sZUFybiB9KTtcbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCBcIkV4dGVybmFsSWRcIiwgeyB2YWx1ZTogZXh0ZXJuYWxJZCB9KTtcbiAgfVxufVxuIl19