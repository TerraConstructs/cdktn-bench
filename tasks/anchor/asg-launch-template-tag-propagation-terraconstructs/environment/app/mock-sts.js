#!/usr/bin/env node
// arms/terraconstructs/environment/app/mock-sts.js
//
// Static fixture, byte-copied into every generated task's
// /app/project/mock-sts.js by generator/gen.py::write_environment()
// (shutil.copytree of this arm's whole environment/app/ tree). NOT
// generated per-scenario -- do not move this into generator/gen.py's
// per-spec output.
//
// Why this exists: terraconstructs' AwsStack.account getter lazily
// creates a REAL `data "aws_caller_identity"` Terraform data source the
// moment any L2 construct references the stack's account (which most do,
// internally, for ARN formatting) -- unlike the provider's own implicit
// account lookup, `skip_requesting_account_id` in providerConfig does NOT
// suppress this explicit data source's STS call. Left unhandled,
// `terraform plan` for ANY non-trivial terraconstructs solution fails
// offline with a 403 (InvalidClientTokenId) against real STS.
//
// This is a minimal, dependency-free (no npm install needed -- `node`
// built-in `http` only) loopback HTTP responder that answers ANY request
// with a fixed, valid `GetCallerIdentity` XML response, regardless of the
// SigV4-signed headers AWS's SDK attaches (this stub never verifies them).
// generator/gen.py's build_static_tiers_sh() starts this on
// 127.0.0.1:<TERRACONSTRUCTS_MOCK_STS_PORT> immediately before `terraform
// plan` and kills it immediately after -- see that file's terraconstructs
// tf-plan step. terraconstructs_main_ts()'s generated main.ts skeleton
// points providerConfig.endpoints.sts at the same port.
//
// Loopback-only: works even under `docker run --network none`, since the
// `lo` interface is always present inside a container's own network
// namespace regardless of external network attachment -- see
// DECISIONS.md "terraconstructs offline `terraform plan` needs a mocked
// STS endpoint".
"use strict";

const http = require("http");

const port = parseInt(process.argv[2] || "17771", 10);

const body = `<?xml version="1.0" encoding="UTF-8"?>
<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <GetCallerIdentityResult>
    <Arn>arn:aws:iam::123456789012:user/cdktn-bench-offline</Arn>
    <UserId>AIDACKCEVSQ6C2EXAMPLE</UserId>
    <Account>123456789012</Account>
  </GetCallerIdentityResult>
  <ResponseMetadata>
    <RequestId>00000000-0000-0000-0000-000000000000</RequestId>
  </ResponseMetadata>
</GetCallerIdentityResponse>`;

const server = http.createServer((_req, res) => {
  res.writeHead(200, { "Content-Type": "text/xml" });
  res.end(body);
});

server.listen(port, "127.0.0.1", () => {
  // stderr, not stdout -- keeps stdout free for terraform's own output in
  // the tf-plan step's log stream.
  console.error(`mock-sts listening on 127.0.0.1:${port}`);
});
