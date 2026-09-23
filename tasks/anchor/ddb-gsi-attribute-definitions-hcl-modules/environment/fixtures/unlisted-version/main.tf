# Preflight fixture 3 of 3: the NEGATIVE one. `init` here must FAIL.
#
# 5.16.1 is the only s3-bucket version in the allowlist. A responder that
# proxied, guessed, or fell through to the public registry would install
# 9.9.9 and the arm's version-selection skill would stop being measured —
# and it would do so silently, because a module that installs is a module
# that plans.
#
# Terraform reads `versions` before it reads `download`, so what fails here is
# constraint selection against the allowlist and the message is terraform's
# own, not the responder's. preflight.sh therefore asserts three things
# together: init exits non-zero, the responder logged the `versions` request
# and NO `download`/`tarballs` request for 9.9.9, and a direct request to the
# download endpoint answers 404 with the responder's own sentence naming the
# newest version it holds. Any one of those alone can be passed by a broken
# environment — a container with no route to the sidecar also fails `init`.
terraform {
  required_version = ">= 1.15"
}

module "unlisted" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "9.9.9"
}
