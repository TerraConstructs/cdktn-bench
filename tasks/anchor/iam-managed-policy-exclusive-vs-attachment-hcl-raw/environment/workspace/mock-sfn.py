#!/usr/bin/env python3
"""arms/hcl-raw/environment/workspace/mock-sfn.py

Static fixture, byte-copied into every generated hcl_raw task's
environment/workspace/ (generator/gen.py::write_environment()'s copytree of
this arm's whole environment/workspace/ tree). NOT generated per-scenario --
do not move this into generator/gen.py's per-spec output.

Why this exists: `hashicorp/aws`'s `aws_sfn_state_machine` resource runs a
REAL `states:ValidateStateMachineDefinition` API call from inside its own
`CustomizeDiff` (`internal/service/sfn/state_machine.go::
stateMachineDefinitionValidate`) every time `definition` changes -- which is
unconditionally true for a brand-new resource. This is NOT suppressed by
`skip_credentials_validation`/`skip_requesting_account_id`/etc. (those only
affect the provider's OWN bootstrap calls, not a resource's own
CustomizeDiff-triggered service call) -- confirmed by reproducing it
directly: `terraform plan` against a real, oracle-correct `aws_sfn_state_machine`
config with only the standard skip_*/dummy-credential fixture fails with
`UnrecognizedClientException: The security token included in the request is
invalid` (verified against the pinned hashicorp/aws 6.58.0; the CustomizeDiff
call is unchanged from when this was first reported upstream, see
github.com/hashicorp/terraform-provider-aws issue #39472). Exactly the same
class of problem `arms/terraconstructs`' `mock-sts.js` fixes for that arm's
`data "aws_caller_identity"` call (see DECISIONS.md "terraconstructs offline
`terraform plan` needs a mocked STS endpoint") -- this is the `hcl_raw`-arm
analogue, for the `states`/`sfn` service instead of `sts`.

No `node` in this arm's image (Debian + terraform/opa/jq/awscli only, per
arms/hcl-raw/environment/Dockerfile's own baseline) -- `python3`'s stdlib
`http.server` is used instead (added to that Dockerfile specifically for
this fixture; no pip package required). This is a dependency-free, minimal,
loopback HTTP responder that answers ANY request with a fixed, valid
`ValidateStateMachineDefinition` JSON response
(`{"result": "OK", "diagnostics": []}` -- the AWS SFN JSON-1.0-protocol
shape `stateMachineDefinitionValidate` checks `output.Result ==
ValidateStateMachineDefinitionResultCodeOk` against), regardless of the
SigV4-signed headers/request body/path the AWS SDK sends (this stub never
verifies or even reads them). generator/gen.py's build_static_tiers_sh()
starts this on 127.0.0.1:<HCL_RAW_MOCK_SFN_PORT> immediately before
`terraform plan` (wrapping the WHOLE hcl_raw plan_command, since `terraform
init`/`validate` don't need it but running it for their duration too is
harmless) and kills it immediately after -- see that file's hcl_raw
tf-plan-mock-sfn step. arms/hcl-raw/environment/workspace/provider.tf's
`endpoints { sfn = "http://127.0.0.1:<port>" }` points at the same port.

Harmless no-op for every OTHER hcl_raw scenario -- i.e. any that never
touches `aws_sfn_state_machine` at all --
same "always started regardless of whether THIS scenario needs it" shape as
terraconstructs' STS mock (see that file's own docstring for the identical
precedent).

Loopback-only: works even under `docker run --network none`, since the `lo`
interface is always present inside a container's own network namespace
regardless of external network attachment.
"""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

BODY = b'{"result":"OK","diagnostics":[]}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _respond(self) -> None:
        # Drain any request body (the AWS SDK always sends one for this
        # JSON-1.0-protocol POST) so keep-alive/pipelining never hangs --
        # this stub answers identically regardless of what was sent.
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-amz-json-1.0")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's own naming convention
        self._respond()

    def do_GET(self) -> None:  # noqa: N802
        self._respond()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        # Quiet by design -- stderr stays free for terraform's own output in
        # the tf-plan-mock-sfn step's log stream (mirrors mock-sts.js's own
        # "stderr, not stdout" convention, one level quieter still: no
        # per-request line at all, only the startup line below).
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 17772
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"mock-sfn listening on 127.0.0.1:{port}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
