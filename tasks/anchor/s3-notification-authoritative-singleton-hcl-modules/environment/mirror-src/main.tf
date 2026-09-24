// Build-time only. Consumed by `terraform providers mirror` while building the
// image (which does have network access at build time) to populate the
// filesystem provider mirror baked into the image. Never used at runtime.
//
// THE UNION, NOT THE SHORTLIST. arms/hcl-raw mirrors `hashicorp/aws` alone
// because the agent hand-writes every resource. Here the agent composes
// `terraform-aws-modules` modules out of /opt/terraform-modules, and a module
// declares its own `required_providers`: `terraform init` fails on a provider
// the mirror lacks even when the module only reaches it through a submodule
// the workspace never calls, because init resolves the whole module tree it
// installs. The eight entries below are derived from the vendored bytes, not
// from a reading of which submodules "should" be reachable: they are every
// distinct `source = "<namespace>/<name>"` under ../modules/ except one.
// generator/tests/test_hcl_modules_image.py recomputes that grep and fails if
// a module refresh introduces a ninth.
//
// Every version below is the newest published at pin time, which satisfies
// every `>=` floor in the tree (the floors are recorded next to each entry).
// `aws` is the exception: it is pinned to the SAME 6.66.0 arms/hcl-raw pins,
// because the two Terraform arms must resolve identical provider schemas or a
// cross-arm score difference could be a provider difference (DECISIONS.md
// Amendment 48).
terraform {
  required_providers {
    // every module; also arms/hcl-raw's pin
    aws = {
      source  = "hashicorp/aws"
      version = "6.66.0"
    }
    // lambda root (>= 1.0)
    external = {
      source  = "hashicorp/external"
      version = "2.4.2"
    }
    // lambda root (>= 1.0)
    local = {
      source  = "hashicorp/local"
      version = "2.9.1"
    }
    // lambda root (>= 2.0), eks//modules/_user_data (>= 3.0)
    null = {
      source  = "hashicorp/null"
      version = "3.3.2"
    }
    // rds//modules/db_instance (>= 3.1), called unconditionally by the rds
    // decoy's root main.tf — the one provider the spec matrix §4b table misses
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
    // eks root (>= 4.0), iam//modules/iam-oidc-provider (>= 3.0)
    tls = {
      source  = "hashicorp/tls"
      version = "4.4.1"
    }
    // eks root (>= 0.9), ecs//modules/cluster (>= 0.13)
    time = {
      source  = "hashicorp/time"
      version = "0.14.2"
    }
    // eks//modules/_user_data (>= 2.0)
    cloudinit = {
      source  = "hashicorp/cloudinit"
      version = "2.4.1"
    }

    // THE ONE EXCLUSION is `kreuzwerker/docker`, declared only by
    // `lambda-8.8.2/modules/docker-build`. That submodule builds container
    // images and needs a Docker daemon the agent container has not got, so it
    // cannot work here whatever the mirror holds — and mirroring it measured
    // 370s of a 415s mirror step (the other eight together take ~45s) against
    // Harbor's 600s build_timeout_sec for a cold task build, which is a voided
    // trial. A workspace naming that submodule fails `init` on the missing
    // provider, which is the loud failure the absent `direct {}` produces.
  }
}
