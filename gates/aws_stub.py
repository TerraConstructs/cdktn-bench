#!/usr/bin/env python3
"""Two-route AWS stub for credential-free host gates.

Answers sts:GetCallerIdentity and states:ValidateStateMachineDefinition.
Everything else -> 400 UnsupportedOperation, logged. Binds an ephemeral port
by default and prints `PORT=<n>` on stdout once listening.

`running_stub()` (bottom of file) is the process-level lifecycle its three
host consumers (gates/oracle_falsifiability.py, gates/grading_proof.py,
generator/check_reference_paths.py) use: it starts
this script as a subprocess ONCE per gate invocation, waits for its
`PORT=<n>` announcement, and yields a full environment dict -- a copy of the
gate's own `os.environ`, every inherited `AWS_*` variable dropped, and
AWS_ENDPOINT_URL/AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_REGION set to
the stub's port and fixed dummy values -- ready to pass as `env=` to every
toolchain subprocess the gate runs (`terraform plan`, `cdktn synth`, and the
generated `tests/static_tiers.sh`'s own `aws sts get-caller-identity`
preflight, aws-access.html's design). This is the ONLY thing that makes
those gates credential-free: with no override, terraform/cdktn/the aws CLI
would otherwise reach for whatever `~/.aws/credentials` or `AWS_PROFILE` the
operator's shell happens to have live, silently coupling gate correctness to
one developer's machine state.
"""
from __future__ import annotations
import contextlib, os, shutil, stat, subprocess, sys, tempfile, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

ACCOUNT = os.environ.get("AWS_STUB_ACCOUNT_ID", "123456789012")
STS = f"""<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <GetCallerIdentityResult><Arn>arn:aws:iam::{ACCOUNT}:user/cdktn-bench-gate</Arn>
  <UserId>AIDACKCEVSQ6C2EXAMPLE</UserId><Account>{ACCOUNT}</Account></GetCallerIdentityResult>
  <ResponseMetadata><RequestId>00000000-0000-0000-0000-000000000000</RequestId></ResponseMetadata>
</GetCallerIdentityResponse>""".encode()
SFN = b'{"result":"OK","diagnostics":[]}'

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _send(self, code, ctype, body):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n) if n else b""
        target = self.headers.get("X-Amz-Target", "")
        action = parse_qs(raw.decode(errors="replace")).get("Action", [""])[0]
        if action == "GetCallerIdentity": return self._send(200, "text/xml", STS)
        if target.endswith(".ValidateStateMachineDefinition"): return self._send(200, "application/x-amz-json-1.0", SFN)
        print(f"UNSUPPORTED target={target!r} action={action!r} path={self.path}", file=sys.stderr, flush=True)
        self._send(400, "application/x-amz-json-1.0", json.dumps({"__type":"UnsupportedOperation","message":f"cdktn-bench aws_stub: {target or action or self.path}"}).encode())
    do_GET = do_POST
    def log_message(self, *a): pass

_SCRIPT = Path(__file__).resolve()

# Fixed, obviously-fake credentials (AWS's own documented example key --
# never a real secret) -- every gate subprocess needs *some* static
# credential pair present or the SDK/CLI/terraform provider falls through to
# instance-metadata/SSO lookups before ever reaching AWS_ENDPOINT_URL.
_DUMMY_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
_DUMMY_SECRET_ACCESS_KEY = "dummy-secret-key-not-real"  # noqa: S105
_REGION = "us-east-1"

# One-file PATH shim used only when `aws` is not already resolvable -- shells
# out to the mise-managed CLI (CLAUDE.md: "aws CLI via mise, never brew").
# The generated tests/static_tiers.sh preflight calls plain `aws`, so this is
# the gate-side equivalent of `mise x aws@latest -- aws` for a script that
# can't itself be edited to know about mise.
_AWS_SHIM = "#!/bin/sh\nexec mise x aws@latest -- aws \"$@\"\n"


@contextlib.contextmanager
def running_stub(account_id: str | None = None):
    """Start this stub ONCE, yield a ready-to-use `env=` dict, tear down on
    exit -- the whole credential-free lifecycle in one place so every gate
    (and every test) shares one implementation instead of re-deriving it.

    The yielded dict is a full copy of the calling process's own `os.environ`
    (never a bare overlay -- a subprocess `env=` kwarg REPLACES the
    environment rather than merging into it, so a partial dict would strip
    PATH/HOME/etc from every toolchain subprocess) with:

      * AWS_ENDPOINT_URL pointed at the freshly bound stub port
      * AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION set to fixed
        dummy values (verified: hashicorp/aws 6.58.0's bare provider block
        and the `aws` CLI both honor AWS_ENDPOINT_URL for every request)
      * EVERY other inherited `AWS_*` variable dropped, so an operator's own
        ambient `~/.aws` state can never leak into a gate run. Scrubbing the
        whole namespace rather than a known list is the point: a
        service-specific `AWS_ENDPOINT_URL_STS` outranks `AWS_ENDPOINT_URL`
        in both the CLI and the provider, and
        AWS_SHARED_CREDENTIALS_FILE / AWS_CONFIG_FILE / AWS_CA_BUNDLE /
        AWS_PROFILE / AWS_SESSION_TOKEN each reach a real endpoint (or break
        TLS) from a differently-configured machine.
      * PATH prepended with a one-file `aws` shim IFF `aws` isn't already on
        PATH (the generated static_tiers.sh preflight step shells out to
        plain `aws`). The shim delegates to `mise x aws@latest -- aws`; with
        neither `aws` nor `mise` resolvable this raises rather than yielding
        an environment whose preflight is guaranteed to fail downstream as an
        unexplained `reward=None`.

    Torn down (subprocess killed, shim dir removed) on any exit, including
    an exception raised inside the `with` block.
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
