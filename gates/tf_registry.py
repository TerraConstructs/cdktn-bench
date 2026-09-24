"""Process-level lifecycle for the offline module registry, for host gates.

`running_registry()` is to arms/hcl-modules/environment/tf-registry/responder.py
what gates/aws_stub.py::running_stub is to the AWS stub: it starts the responder
once per gate invocation on an ephemeral loopback port, writes the
`TF_CLI_CONFIG_FILE` that points terraform at it, and yields the environment
every toolchain subprocess must use.

The written CLI config CONCATENATES whatever config the caller's environment
already names (the arm's `provider_installation { filesystem_mirror … }` block)
with the `host "registry.terraform.io"` override. Concatenation rather than
replacement is the point: the two blocks are independent, and dropping the
provider block to gain the module override would send provider installation
back to the network — the coupling this arm exists to avoid.

`hcl_modules` is the only arm that gets it: `arm_env()` below is the one place
that decides so, and every host gate that runs a fixture goes through it, so two
gates cannot start the same fixture in different environments. Every other arm's
environment is handed back unchanged. See docs/gates.md#tf-registry.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESPONDER = REPO_ROOT / "arms" / "hcl-modules" / "environment" / "tf-registry" / "responder.py"
MODULES_ROOT = REPO_ROOT / "arms" / "hcl-modules" / "environment" / "modules"

# Where a caller (the e2e test, a debugging operator) reads back which requests
# the responder actually served -- the only proof that a module came from here
# and not from registry.terraform.io.
LOG_VAR = "CDKTN_BENCH_TF_REGISTRY_LOG"
URL_VAR = "CDKTN_BENCH_TF_REGISTRY_URL"

_HOST_BLOCK = """
// Forces registry.terraform.io's modules.v1 service at the loopback responder,
// with no discovery request and no TLS. Plain HTTP is legal here only because
// the override exists: without it Terraform always discovers over HTTPS.
//
// providers.v1 is restated at its real URL because a `host` block REPLACES the
// whole service map: overriding modules alone makes Terraform report that
// registry.terraform.io "does not offer a Terraform provider registry" and fail
// init on the provider stage. In the arm image the filesystem_mirror answers
// providers and this line is never reached; on the host, where no mirror
// exists, it is what keeps provider installation working exactly as it does for
// the other three Terraform-shaped arms.
host "registry.terraform.io" {{
  services = {{
    "modules.v1"   = "http://127.0.0.1:{port}/v1/modules/"
    "providers.v1" = "https://registry.terraform.io/v1/providers/"
  }}
}}

disable_checkpoint = true
"""


def cli_config_text(port: int, inherited: Path | None) -> str:
    """The CLI config body: the inherited config's bytes, then the override."""
    prefix = ""
    if inherited is not None and inherited.is_file():
        prefix = inherited.read_text().rstrip("\n") + "\n"
    return prefix + _HOST_BLOCK.format(port=port)


@contextlib.contextmanager
def running_registry(
    root: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> Iterator[dict[str, str]]:
    """Start the responder over `root`, yield a ready-to-use `env=` dict.

    `env` defaults to the calling process's own environment and is copied, never
    mutated: a subprocess `env=` kwarg REPLACES the environment rather than
    merging into it, so the yielded dict has to be complete. The responder
    subprocess is terminated and the temporary directory holding the CLI config
    and the access log removed on any exit, including an exception raised inside
    the `with` block -- so a caller reads `CDKTN_BENCH_TF_REGISTRY_LOG` while the
    block is still open.
    """
    root = Path(MODULES_ROOT if root is None else root)
    if not (root / "manifest.json").is_file():
        raise RuntimeError(
            f"no manifest.json under {root} -- the vendored module tree is what "
            "the responder serves, so a gate cannot run this arm without it "
            "(refresh it with scripts/vendor_modules.py)"
        )
    base = dict(os.environ if env is None else env)
    tmp = tempfile.mkdtemp(prefix="cdktn-bench-tf-registry-")
    pump: threading.Thread | None = None
    log_path = Path(tmp) / "access.log"
    log = log_path.open("w")
    proc = subprocess.Popen(
        [sys.executable, str(RESPONDER), "--root", str(root), "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=log,
        text=True,
        env=base,
    )
    try:
        port_line = proc.stdout.readline() if proc.stdout else ""
        if not port_line.startswith("PORT="):
            proc.terminate()
            raise RuntimeError(
                f"responder.py did not announce a port on startup (expected "
                f"'PORT=<n>', got {port_line!r}) -- it may have failed to bind "
                "127.0.0.1:0 or to read the manifest"
            )
        port = int(port_line.strip().removeprefix("PORT="))
        # The ACCESS lines the responder prints are drained on a thread: its
        # stdout pipe fills after a few hundred requests, and a blocked write
        # there stalls `terraform init` mid-download with no error.
        pump = _pump(proc, log)
        config = Path(tmp) / "cli.tfrc"
        inherited = base.get("TF_CLI_CONFIG_FILE")
        config.write_text(cli_config_text(port, Path(inherited) if inherited else None))
        result = dict(base)
        result[URL_VAR] = f"http://127.0.0.1:{port}"
        result[LOG_VAR] = str(log_path)
        result["TF_CLI_CONFIG_FILE"] = str(config)
        yield result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        if pump is not None:
            pump.join(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


# The only arm whose toolchain needs more than the AWS stub: its modules resolve
# from the loopback registry, never from registry.terraform.io.
REGISTRY_ARM = "hcl_modules"


@contextlib.contextmanager
def arm_env(arm: str, env: dict[str, str]) -> Iterator[dict[str, str]]:
    """`env` for one arm's toolchain runs; unchanged for every arm but this one.

    `hcl_modules` additionally runs under `running_registry`, which adds the
    `TF_CLI_CONFIG_FILE` whose `host` override points `registry.terraform.io`'s
    modules service at the loopback responder. Without it this arm's `terraform
    init` resolves its modules from the PUBLIC registry, so a gate would grade a
    solution the arm's own offline image cannot build -- or pass one the network
    happened to supply. Other arms declare no modules, so handing them that
    config would only couple green arms to a fourth arm's subprocess.

    Lives beside `running_registry` rather than in any one gate, because four
    callers now need it -- gates/oracle_falsifiability.py, gates/grading_proof.py,
    gates/artifact_collector.py and generator/check_reference_paths.py -- and a
    gate that half-knew about the registry would resolve modules from the network
    and call the result offline.
    """
    if arm != REGISTRY_ARM:
        yield env
        return
    with running_registry(env=env) as registry_env:
        yield registry_env


def _pump(proc: subprocess.Popen, log) -> threading.Thread:
    def run() -> None:
        for line in proc.stdout:
            log.write(line)
            log.flush()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
