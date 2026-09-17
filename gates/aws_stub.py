#!/usr/bin/env python3
"""Three-route AWS stub for credential-free host gates.

Answers sts:GetCallerIdentity, iam:GetRole and
states:ValidateStateMachineDefinition; everything else -> 400
UnsupportedOperation, logged. Binds an ephemeral port by default and prints
`PORT=<n>` on stdout once listening.

The identity is an assumed role, the shape every live trial holds; an IAM-user
ARN would let an artifact embedding the caller ARN pass on a shape no trial
produces. iam:GetRole answers that one role, since `aws_iam_session_context`
resolves a session ARN through it and fails the plan on any error.

`running_stub()` (bottom of file) is the process-level lifecycle its three host
consumers (gates/oracle_falsifiability.py, gates/grading_proof.py,
generator/check_reference_paths.py) use: it starts this script once per gate
invocation and yields the environment every toolchain subprocess must use.
Without it, terraform/cdktn/the aws CLI reach for whatever credentials the
operator's shell has live, coupling gate correctness to one machine's state.
See docs/gates.md#aws-stub.
"""
from __future__ import annotations
import contextlib, os, shutil, stat, subprocess, sys, tempfile, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote

ACCOUNT = os.environ.get("AWS_STUB_ACCOUNT_ID", "123456789012")
GATE_ROLE = "cdktn-bench-gate"
GATE_SESSION = "gate-session"
GATE_ROLE_ID = "AROACKCEVSQ6C2EXAMPLE"
STS = f"""<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <GetCallerIdentityResult><Arn>arn:aws:sts::{ACCOUNT}:assumed-role/{GATE_ROLE}/{GATE_SESSION}</Arn>
  <UserId>{GATE_ROLE_ID}:{GATE_SESSION}</UserId><Account>{ACCOUNT}</Account></GetCallerIdentityResult>
  <ResponseMetadata><RequestId>00000000-0000-0000-0000-000000000000</RequestId></ResponseMetadata>
</GetCallerIdentityResponse>""".encode()

# The trust policy is url-encoded in a real GetRoleResponse; the AWS SDKs
# url-decode it before handing it to a caller, so a literal JSON body here
# would decode into mojibake for any consumer that looks at it.
_TRUST_POLICY = quote(
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",'
    f'"Principal":{{"AWS":"arn:aws:iam::{ACCOUNT}:root"}},'
    '"Action":"sts:AssumeRole"}]}'
)
IAM_ROLE = f"""<GetRoleResponse xmlns="https://iam.amazonaws.com/doc/2010-05-08/">
  <GetRoleResult><Role>
    <Path>/</Path><RoleName>{GATE_ROLE}</RoleName><RoleId>{GATE_ROLE_ID}</RoleId>
    <Arn>arn:aws:iam::{ACCOUNT}:role/{GATE_ROLE}</Arn>
    <CreateDate>2020-01-01T00:00:00Z</CreateDate>
    <MaxSessionDuration>3600</MaxSessionDuration>
    <AssumeRolePolicyDocument>{_TRUST_POLICY}</AssumeRolePolicyDocument>
  </Role></GetRoleResult>
  <ResponseMetadata><RequestId>00000000-0000-0000-0000-000000000000</RequestId></ResponseMetadata>
</GetRoleResponse>""".encode()


def _no_such_role(name: str) -> bytes:
    return f"""<ErrorResponse xmlns="https://iam.amazonaws.com/doc/2010-05-08/">
  <Error><Type>Sender</Type><Code>NoSuchEntity</Code>
  <Message>The role with name {name} cannot be found.</Message></Error>
  <RequestId>00000000-0000-0000-0000-000000000000</RequestId>
</ErrorResponse>""".encode()


SFN = b'{"result":"OK","diagnostics":[]}'

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _send(self, code, ctype, body):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n) if n else b""
        target = self.headers.get("X-Amz-Target", "")
        form = parse_qs(raw.decode(errors="replace"))
        action = form.get("Action", [""])[0]
        if action == "GetCallerIdentity": return self._send(200, "text/xml", STS)
        if action == "GetRole":
            name = form.get("RoleName", [""])[0]
            # Only the one role this stub's own caller identity assumes exists.
            # Answering any name would let a plan resolve an issuer role that
            # the account does not hold, which is a fake success.
            if name == GATE_ROLE: return self._send(200, "text/xml", IAM_ROLE)
            return self._send(404, "text/xml", _no_such_role(name))
        if target.endswith(".ValidateStateMachineDefinition"): return self._send(200, "application/x-amz-json-1.0", SFN)
        print(f"UNSUPPORTED target={target!r} action={action!r} path={self.path}", file=sys.stderr, flush=True)
        self._send(400, "application/x-amz-json-1.0", json.dumps({"__type":"UnsupportedOperation","message":f"cdktn-bench aws_stub: {target or action or self.path}"}).encode())
    do_GET = do_POST
    def log_message(self, *a): pass

_SCRIPT = Path(__file__).resolve()

# Fixed, obviously-fake credentials (AWS's own documented example key, never a
# real secret). Every gate subprocess needs *some* static credential pair
# present or the SDK/CLI/terraform provider falls through to
# instance-metadata/SSO lookups before ever reaching AWS_ENDPOINT_URL.
_DUMMY_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
_DUMMY_SECRET_ACCESS_KEY = "dummy-secret-key-not-real"  # noqa: S105
_REGION = "us-east-1"

# One-file PATH shim, used only when `aws` is not already resolvable. The
# generated tests/static_tiers.sh preflight calls plain `aws`, so this is the
# gate-side equivalent of the repo's `mise x aws@latest -- aws` rule for a
# script that cannot itself be edited to know about mise.
_AWS_SHIM = "#!/bin/sh\nexec mise x aws@latest -- aws \"$@\"\n"


@contextlib.contextmanager
def running_stub(account_id: str | None = None):
    """Start this stub ONCE, yield a ready-to-use `env=` dict, tear down on exit.

    The yielded dict is a full copy of the calling process's own `os.environ`
    (never a bare overlay -- a subprocess `env=` kwarg REPLACES the environment
    rather than merging into it, so a partial dict would strip PATH/HOME/etc
    from every toolchain subprocess) with:

      * AWS_ENDPOINT_URL pointed at the freshly bound stub port, and
        AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION set to fixed
        dummy values. Both the aws CLI and the hashicorp/aws provider honor
        AWS_ENDPOINT_URL for every request.
      * EVERY other inherited `AWS_*` variable dropped, so an operator's own
        ambient `~/.aws` state can never leak into a gate run. Scrubbing the
        whole namespace rather than a known list is the point: a
        service-specific `AWS_ENDPOINT_URL_STS` outranks `AWS_ENDPOINT_URL` in
        both the CLI and the provider, and AWS_SHARED_CREDENTIALS_FILE /
        AWS_CONFIG_FILE / AWS_CA_BUNDLE / AWS_PROFILE / AWS_SESSION_TOKEN each
        reach a real endpoint (or break TLS) from a differently-configured
        machine.
      * PATH prepended with a one-file `aws` shim IFF `aws` isn't already on
        PATH (the generated static_tiers.sh preflight shells out to plain
        `aws`). The shim delegates to `mise x aws@latest -- aws`; with neither
        `aws` nor `mise` resolvable this raises rather than yielding an
        environment whose preflight is guaranteed to fail downstream as an
        unexplained `reward=None`.

    Torn down (subprocess killed, shim dir removed) on any exit, including an
    exception raised inside the `with` block.
    """
    env = dict(os.environ)
    if account_id:
        env["AWS_STUB_ACCOUNT_ID"] = account_id
    proc = subprocess.Popen(
        [sys.executable, str(_SCRIPT)],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    shim_dir: str | None = None
    try:
        port_line = proc.stdout.readline() if proc.stdout else ""
        rest = port_line.strip()
        if not rest.startswith("PORT="):
            proc.terminate()
            raise RuntimeError(
                f"aws_stub.py did not announce a port on startup (expected "
                f"'PORT=<n>', got {port_line!r}) -- stub subprocess may have "
                "failed to bind 127.0.0.1:0"
            )
        port = int(rest.removeprefix("PORT="))

        result_env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
        result_env.update(
            AWS_ENDPOINT_URL=f"http://127.0.0.1:{port}",
            AWS_ACCESS_KEY_ID=_DUMMY_ACCESS_KEY_ID,
            AWS_SECRET_ACCESS_KEY=_DUMMY_SECRET_ACCESS_KEY,
            AWS_REGION=_REGION,
        )

        if shutil.which("aws") is None:
            if shutil.which("mise") is None:
                raise RuntimeError(
                    "no `aws` CLI on PATH and no `mise` to shim one -- the "
                    "generated tests/static_tiers.sh preflight calls plain "
                    "`aws sts get-caller-identity` and would write "
                    "/logs/verifier/aws-unavailable with no reward.txt, "
                    "surfacing as a bare `reward=None` failure. Install the "
                    "CLI (CLAUDE.md: `mise x aws@latest -- aws`, never brew)."
                )
            shim_dir = tempfile.mkdtemp(prefix="cdktn-bench-aws-shim-")
            shim_path = Path(shim_dir) / "aws"
            shim_path.write_text(_AWS_SHIM)
            shim_path.chmod(shim_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            result_env["PATH"] = f"{shim_dir}{os.pathsep}{result_env.get('PATH', '')}"

        yield result_env
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        if shim_dir is not None:
            shutil.rmtree(shim_dir, ignore_errors=True)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    # Threaded: the aws provider keeps HTTP/1.1 connections alive and issues
    # requests in parallel; a single-threaded server would block on the first
    # idle keep-alive socket and never accept the second connection.
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    print(f"PORT={srv.server_address[1]}", flush=True)
    srv.serve_forever()
