This workspace holds the storage for one internal application: a bucket
that holds the application's own data, and a second bucket that receives
that bucket's S3 server access logs under the `app-data/` prefix. It is
already deployed in this account.

Our security baseline no longer permits this account to rely on S3 access
control lists, and the access-logs bucket in this workspace is one of the
last buckets still using them. Turn access control lists off on that
bucket, then roll the change out to this account with your toolchain's
real deploy command.

The application bucket's server access logs must still be delivered to the
access-logs bucket, under the same `app-data/` prefix, when you are done.

This workspace is hand-written Terraform HCL (no modules).

`main.tf` in this workspace holds this project's existing configuration -- change it as needed. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to change.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
