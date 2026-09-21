"""Run the REAL generated Python verifier in a sandbox, offline.

`gen.write_tests_dir` emits the whole oracle directory -- tests/tiers.py,
tests/verify.py, the two shims, the tier-0 driver and the canonical policy -- so
a test that wants to know what the verifier DOES stages that directory here and
executes it, rather than asserting on emitted text. Nothing reaches AWS: `aws`,
`terraform`, `npm`, `npx` and `node` are stubs on the sandbox's own PATH.

The two in-container paths are repointed by rewriting the shim, which is exactly
how gates/oracle_falsifiability.py and generator/check_reference_paths.py do it;
a test that bypassed the shim would stop testing that mechanism.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import task_dir, write_tests_dir  # noqa: E402
from spec_model import Arm, Spec, Step  # noqa: E402

STUB_TOOLS = ("terraform", "npm", "npx", "node", "cdk")


@dataclass
class Result:
    rc: int
    stdout: str
    stderr: str
    logs: Path

    @property
    def reward(self) -> str | None:
        f = self.logs / "reward.txt"
        return f.read_text() if f.is_file() else None

    @property
    def markers(self) -> list[str]:
        return sorted(p.name for p in self.logs.iterdir() if p.is_file())

    def marker(self, name: str) -> str | None:
        f = self.logs / name
        return f.read_text() if f.is_file() else None

    def result_json(self, name: str) -> dict:
        return json.loads((self.logs / name).read_text())

    @property
    def summary(self) -> str | None:
        m = re.search(r"== summary: tier0_pass=(\d) tier1_status=(\S+) ==", self.stdout)
        return m.group(0) if m else None

    @property
    def tier1_status(self) -> str | None:
        m = re.search(r"tier1_status=(\S+)", self.stdout)
        return m.group(1) if m else None

    @property
    def tier0_pass(self) -> str | None:
        m = re.search(r"tier0_pass=(\d)", self.stdout)
        return m.group(1) if m else None


class Box:
    """One staged task directory, with the verifier's paths inside the sandbox."""

    def __init__(self, root: Path, spec: Spec, arm: Arm, step: Step | None):
        self.root = root
        self.project = root / "app" / "project"
        self.tests = self.project / "tests"
        self.logs = root / "logs" / "verifier"
        self.bins = root / "bin"
        self.receipt = root / "logs" / "seed-deploy-receipt.json"
        for d in (self.project, self.logs, self.bins):
            d.mkdir(parents=True, exist_ok=True)
        self._seed_hand_authored(spec, arm, step)
        write_tests_dir(spec, arm, self.tests, step)
        self._repoint()
        for tool in STUB_TOOLS:
            self.stub(tool, "exit 0")
        self.stub("aws", "exit 0")

    def _seed_hand_authored(self, spec: Spec, arm: Arm, step: Step | None) -> None:
        """A spec that declares `hand_authored` has no stub for the generator to
        write, and write_tests_dir refuses to invent one -- so the real oracle is
        copied in first, exactly as it reaches a task dir."""
        if not spec.verifier.live_check.hand_authored:
            return
        real = task_dir(spec, arm)
        if step is not None:
            real = real / "steps" / step.name
        src = real / "tests" / "live_check.py"
        if src.is_file():
            self.tests.mkdir(parents=True, exist_ok=True)
            self.tests.joinpath("live_check.py").write_bytes(src.read_bytes())

    def _repoint(self) -> None:
        # verify.py joins the shims here because a live tier's command names the
        # project path absolutely (an arm whose state file is not under the
        # synthesized stack dir re-probes it by full path).
        for name in ("static_tiers.sh", "test.sh", "verify.py"):
            f = self.tests / name
            text = f.read_text()
            text = text.replace("/logs/verifier", str(self.logs))
            text = text.replace("/app/project", str(self.project))
            text = text.replace("/logs/seed-deploy-receipt.json", str(self.receipt))
            f.write_text(text)
            f.chmod(0o755)

    # --- staging ---------------------------------------------------------

    def stub(self, name: str, body: str) -> Path:
        """A stand-in on the sandbox's PATH, ahead of anything real."""
        p = self.bins / name
        p.write_text("#!/usr/bin/env bash\n" + body + "\n")
        p.chmod(0o755)
        return p

    def drop(self, *names: str) -> None:
        for name in names:
            (self.tests / name).unlink(missing_ok=True)

    def config(self) -> dict:
        return read_config(self.tests / "verify.py")

    def patch_config(self, **overrides) -> None:
        """Rewrite CONFIG, for a test that needs a fault the spec cannot express
        (an artifact that never lands, a toolchain that fails)."""
        cfg = self.config()
        cfg.update(overrides)
        text = (self.tests / "verify.py").read_text()
        head = text[: text.index("CONFIG = ")]
        self.tests.joinpath("verify.py").write_text(
            head + "CONFIG = " + repr(cfg) + "\n\n"
            "raise SystemExit(tiers.main(CONFIG, sys.argv[1:]))\n"
        )

    def static_tiers(self, verdict: str) -> None:
        """Make the static tiers report exactly `verdict` ("1.0" or "0.0"), so a
        test about a LATER tier is not also a test of this spec's oracle.

        The toolchain and the preflight are dropped, the artifact is staged, and
        the tier-0 driver is replaced by its own exit code -- the same lever the
        bash-era tests pulled by stubbing static_tiers.sh, one layer in.
        """
        cfg = self.config()
        tier1 = dict(cfg["tier1"], has_asserts=False)
        self.patch_config(aws_preflight=False, toolchain=[], tier1=tier1)
        self.artifact({})
        self.tests.joinpath("tier0.py").write_text(
            "raise SystemExit(%d)\n" % (0 if verdict == "1.0" else 1)
        )

    def artifact(self, document: dict | str) -> Path:
        """Stage the document the toolchain would have produced."""
        rel = self.config()["artifact"]
        p = self.project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(document if isinstance(document, str) else json.dumps(document))
        return p

    def seed_receipt(self, **fields) -> Path:
        self.receipt.parent.mkdir(parents=True, exist_ok=True)
        self.receipt.write_text(json.dumps(fields))
        return self.receipt

    # --- running ---------------------------------------------------------

    def run(self, script: str = "test.sh", env: dict | None = None,
            only_stub_path: bool = False) -> Result:
        path = str(self.bins)
        if not only_stub_path:
            path += os.pathsep + os.environ["PATH"]
        run_env = {**os.environ, "PATH": path}
        run_env.pop("AWS_DEFAULT_REGION", None)
        run_env.update(env or {})
        proc = subprocess.run(
            ["bash", str(self.tests / script)],
            cwd=self.project, capture_output=True, text=True, env=run_env,
        )
        return Result(proc.returncode, proc.stdout, proc.stderr, self.logs)

    def tiers(self):
        """tests/tiers.py imported with the sandbox's own paths, for a unit-level
        call into one tier."""
        os.environ["CDKTN_VERIFIER_LOGS_DIR"] = str(self.logs)
        os.environ["CDKTN_VERIFIER_PROJECT_DIR"] = str(self.project)
        os.environ["CDKTN_VERIFIER_SEED_RECEIPT"] = str(self.receipt)
        spec = importlib.util.spec_from_file_location(
            f"tiers_{abs(hash(str(self.root)))}", self.tests / "tiers.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def read_config(verify_py: Path) -> dict:
    """The CONFIG literal an already-generated tests/verify.py declares."""
    for node in ast.parse(verify_py.read_text()).body:
        if isinstance(node, ast.Assign) and node.targets[0].id == "CONFIG":
            return ast.literal_eval(node.value)
    raise AssertionError(f"{verify_py} declares no CONFIG")


def stage(tmp_path: Path, spec: Spec, arm: Arm, step: Step | None = None,
          *, name: str = "") -> Box:
    return Box(tmp_path / (name or f"{spec.id}-{arm}"), spec, arm, step)
