#!/usr/bin/env python3
"""Zero-drift gate on the plan normaliser: every existing Terraform fixture
must grade identically with and without it.

The normaliser (tests/tiers.py::normalise_plan) hoists module resources into
`planned_values.root_module.resources`, the shape every tier-0 JSONPath and
every Rego policy already addresses. It runs on both Terraform-shaped arms for
every spec, not only the module ones, so the whole corpus's grading now flows
through it -- and the corpus has no module in it. This gate is the proof that
nothing moved: for each collected artifact it grades the RAW document and the
NORMALISED one and demands

  * identical per-assert tier-0 outcomes, all three values;
  * identical tier-1 `deny` and `not_verifiable` sets;
  * canonical (sorted-key) byte identity of raw vs normalised.

A MODULE-SHAPED fixture is held to a different contract, because on one the
normaliser is supposed to change the grading -- that is the whole mechanism.
There the requirement is only that it changes it in the LOUD direction: an
assert may move off `unresolvable`, which is the module resource becoming
visible, and may never move ONTO it, which would be a grader going blind. Its
tier-1 sets and its bytes are reported rather than required, and whether its
reward still lands where the spec says belongs to `make falsifiability`.

Exit 0 = no drift. 1 = drift, or an artifact that could not be graded at all.
3 = nothing was gradeable, the repo's NOT_AUTHORED convention.

Usage: a spec path, `--all`, or `--regrade DIR` over a tree `--out` kept; the
rest is docs/gates.md#normaliser-parity.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))
sys.path.insert(0, str(REPO_ROOT / "gates"))

import artifact_collector as ac  # noqa: E402
from aws_stub import running_stub  # noqa: E402
from gen import ARM_DIRNAME, TIERS_PY  # noqa: E402
from spec_model import Arm, Spec, load_spec  # noqa: E402
from tier0_parity import grade_driver, tier0_asserts  # noqa: E402

# The arms whose CONFIG declares `normalise_plan`. An awscdk task grades a
# CloudFormation template and never calls the normaliser, so re-grading one
# here would report agreement about a mechanism that did not run.
NORMALISING_ARMS: tuple[Arm, ...] = ("hcl_raw", "terraconstructs")


def load_normaliser():
    """The normaliser a task ships, imported from the generator's own template
    rather than from a task dir: this gate has to run before the corpus is
    regenerated as well as after."""
    path = Path(tempfile.mkdtemp(prefix="normaliser-")) / "tiers.py"
    path.write_text(TIERS_PY)
    spec = importlib.util.spec_from_file_location("normaliser_tiers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(document) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def opa_sets(policy: Path, pkg: str, artifact: Path, extra: list[Path]) -> dict:
    """The tier-1 `deny` and `not_verifiable` sets one policy produces over one
    document, as SETS of messages: the rule fired or it did not, and the order
    OPA returns them in is not part of the contract."""
    out = {}
    for rule in ("deny", "not_verifiable"):
        argv = ["opa", "eval", "-f", "raw", "-I", "-d", str(policy)]
        for lib in extra:
            argv += ["-d", str(lib)]
        argv.append("data.cdktn_bench.%s.%s" % (pkg, rule))
        with artifact.open("rb") as src:
            proc = subprocess.run(argv, stdin=src, capture_output=True, text=True)
        if proc.returncode != 0:
            # An aborted evaluation is a fact about this gate's pair, not a
            # verdict: it has to be comparable, so it is recorded rather than
            # raised.
            out[rule] = ["ENGINE_ERROR: %s" % proc.stderr.strip()]
            continue
        text = proc.stdout.strip()
        try:
            value = json.loads(text) if text else []
        except ValueError:
            value = ["UNPARSEABLE: %s" % text]
        out[rule] = sorted(str(v) for v in (value or []))
    return out


def tier0_changes(before: dict, after: dict, modular: bool):
    """(allowed, drift) over one artifact's per-assert tier-0 outcomes.

    On a module-free plan nothing may move: that is the zero-drift contract,
    and every existing fixture's reward rides on it. On a MODULE-shaped plan
    the raw document hides the resource, so the assert that reads it cannot be
    answered at all -- the normaliser making it answerable is the mechanism
    working. Only the reverse, an assert falling back TO `unresolvable`, is a
    grader going blind, and that is drift on any plan.
    """
    moved, drift = [], []
    for name in sorted(set(before) | set(after)):
        raw_outcome = before.get(name, "<absent>")
        new_outcome = after.get(name, "<absent>")
        if raw_outcome == new_outcome:
            continue
        line = "tier-0 %s: raw=%s normalised=%s" % (name, raw_outcome, new_outcome)
        if modular and new_outcome != "unresolvable":
            moved.append(line)
        else:
            drift.append(line)
    return moved, drift


@dataclass
class Cell:
    """One collected artifact, graded raw and normalised."""

    label: str
    arm: str
    fixture: str
    asserts: int = 0
    modular: bool = False
    identical: bool | None = None
    tier1: bool = False
    # What the normaliser legitimately changed on a module-shaped plan: never
    # silent, never a failure. Empty on every module-free plan by construction.
    moved: list[str] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def skipped(self) -> bool:
        """A fixture whose toolchain produced no plan at all is not this gate's
        subject. Any OTHER note is a cell that should have been graded and was
        not, which is a failure here and not a quiet omission."""
        return self.note.startswith("NO_ARTIFACT")

    def render(self) -> str:
        if self.note:
            return "[%s] %s: %s" % ("SKIP" if self.skipped else "FAIL",
                                    self.label, self.note)
        if self.drift:
            return "[FAIL] %s:\n%s" % (
                self.label, "\n".join("        " + d for d in self.drift)
            )
        head = (
            "[PASS] %s: %d assert(s), tier-1 %s, %s"
            % (
                self.label,
                self.asserts,
                "compared" if self.tier1 else "no policy",
                "MODULE-SHAPED: graded on the normalised document only"
                if self.modular
                else "byte-identical raw vs normalised",
            )
        )
        if not self.moved:
            return head
        return head + "\n" + "\n".join(
            "        the hoist changed, in the loud direction: " + m
            for m in self.moved)


def grade_cell(normaliser, spec: Spec, arm: Arm, step, label: str, fixture: str,
               tests: Path, artifact: Path, scratch: Path) -> Cell:
    cell = Cell(label=label, arm=ARM_DIRNAME[arm], fixture=fixture)
    raw = json.loads(artifact.read_text())
    normalised = normaliser.normalise_plan(raw)
    cell.modular = normaliser.is_modular(raw)
    cell.identical = canonical(normalised) == canonical(raw)
    if not cell.modular and not cell.identical:
        cell.drift.append(
            "a plan with no module in it did not normalise to itself -- every "
            "existing fixture's grading moves with it"
        )
    scratch.mkdir(parents=True, exist_ok=True)
    other = scratch / "plan.normalised.json"
    # The same bytes the verifier writes, key order included.
    other.write_text(json.dumps(normalised, indent=2) + "\n")

    asserts = tier0_asserts(spec, arm, step)
    cell.asserts = len(asserts)
    before = grade_driver(tests / "ops.py", asserts, artifact)
    after = grade_driver(tests / "ops.py", asserts, other)
    moved, drift = tier0_changes(before, after, cell.modular)
    cell.moved.extend(moved)
    cell.drift.extend(drift)

    policy = tests / "policy.rego"
    if policy.is_file():
        pkg = spec.id.replace("-", "_")
        extra = [tests / "hcl_traversal.rego"] if (tests / "hcl_traversal.rego").is_file() else []
        t1_before = opa_sets(policy, pkg, artifact, extra)
        t1_after = opa_sets(policy, pkg, other, extra)
        cell.tier1 = True
        for rule in ("deny", "not_verifiable"):
            if t1_before[rule] == t1_after[rule]:
                continue
            line = "tier-1 %s: raw=%s normalised=%s" % (
                rule, t1_before[rule], t1_after[rule])
            # Same reason as tier 0: a policy that could not see a module
            # resource can now see it, so its verdict is ALLOWED to move here.
            # Where it should land is the spec's question, not this gate's.
            (cell.moved if cell.modular else cell.drift).append(line)
    return cell


def run_spec(normaliser, spec: Spec, spec_path: Path, env: dict[str, str],
             keep: ac.KeptTempDir, out: Path | None, manifest: list[dict]) -> list[Cell]:
    cells: list[Cell] = []
    for c in ac.collect(spec, env, keep, arms=NORMALISING_ARMS,
                        require_tests=("ops.py", "tier0.py")):
        if c.plan is None:
            cells.append(Cell(label=c.label, arm=ARM_DIRNAME[c.arm], fixture=c.fixture,
                              note="NO_ARTIFACT (toolchain produced none; reward=%s)"
                                   % c.reward))
            continue
        try:
            cell = grade_cell(normaliser, spec, c.arm, c.step, c.label, c.fixture,
                              c.tests, c.plan,
                              (c.workdir or c.plan.parent) / "normaliser-parity")
        except (ValueError, OSError, RuntimeError, normaliser.NormaliseError) as exc:
            cell = Cell(label=c.label, arm=ARM_DIRNAME[c.arm], fixture=c.fixture)
            cell.drift.append("could not grade both documents: %s" % exc)
        cells.append(cell)
        if out is not None:
            dest = out / ("%s.json" % cell.label.replace("/", "__"))
            dest.write_bytes(c.plan.read_bytes())
            manifest.append({
                "label": c.label, "spec": str(spec_path.relative_to(REPO_ROOT)),
                "arm": c.arm, "fixture": c.fixture,
                "step": c.step.name if c.step else None,
                "tests": str(c.tests.relative_to(REPO_ROOT)),
                "artifact": dest.name, "reward": c.reward, "seconds": c.seconds,
            })
            (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print("  " + cell.render(), flush=True)
    return cells


def regrade(normaliser, tree: Path) -> list[Cell]:
    """Re-grade a tree `--out` wrote, with no toolchain: the normaliser and the
    policies are read from the working copy, the artifacts from disk."""
    cells: list[Cell] = []
    for row in json.loads((tree / "manifest.json").read_text()):
        spec = load_spec(REPO_ROOT / row["spec"])
        step = None
        if row["step"] is not None:
            step = next(s for s in (spec.steps or []) if s.name == row["step"])
        try:
            cell = grade_cell(normaliser, spec, row["arm"], step, row["label"],
                              row["fixture"], REPO_ROOT / row["tests"],
                              tree / row["artifact"],
                              tree / "normaliser-parity" / row["label"].replace("/", "__"))
        except (ValueError, OSError, RuntimeError, normaliser.NormaliseError) as exc:
            cell = Cell(label=row["label"], arm=row["arm"], fixture=row["fixture"])
            cell.drift.append("could not grade both documents: %s" % exc)
        cells.append(cell)
        print("  " + cell.render(), flush=True)
    return cells


def summarise(cells: list[Cell]) -> int:
    graded = [c for c in cells if not c.note]
    bad = [c for c in cells if c.drift or (c.note and not c.skipped)]
    print("")
    print("=== normaliser-parity: raw vs normalised, per spec/arm/fixture ===")
    for c in cells:
        print(c.render())
    print("")
    print(
        "graded %d artifact(s), %d assert evaluation(s) per column; "
        "%d module-shaped, %d byte-identical, %d skipped, %d failed"
        % (
            len(graded), sum(c.asserts for c in graded),
            sum(1 for c in graded if c.modular),
            sum(1 for c in graded if c.identical),
            sum(1 for c in cells if c.skipped), len(bad),
        )
    )
    if bad:
        print("normaliser-parity: FAILED -- the normalised document grades "
              "differently, or an artifact could not be graded at all",
              file=sys.stderr)
        return 1
    if not graded:
        print("normaliser-parity: NOT_AUTHORED -- no fixture produced a "
              "gradeable artifact")
        return 3
    print("normaliser-parity: OK -- every graded artifact grades identically "
          "raw and normalised")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec", nargs="?", type=Path)
    ap.add_argument("--all", action="store_true", help="every specs/*.yaml")
    ap.add_argument("--out", type=Path, help="keep the collected artifacts here")
    ap.add_argument("--work-dir", type=Path, help="keep each fixture's working copy here")
    ap.add_argument("--regrade", type=Path,
                    help="re-grade a tree --out wrote; runs no toolchain")
    args = ap.parse_args(argv)

    normaliser = load_normaliser()
    if args.regrade:
        return summarise(regrade(normaliser, args.regrade))

    if args.all:
        spec_paths = [p for p in sorted(REPO_ROOT.glob("specs/*.yaml"))
                      if p.name != "split.yaml"]
    elif args.spec:
        spec_paths = [args.spec]
    else:
        ap.error("pass a spec path, --all, or --regrade DIR")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    fallback = Path(tempfile.gettempdir()) / "normaliser-parity-work"
    work = args.work_dir or (args.out / "work" if args.out else fallback)
    keep = ac.install(work)

    cells: list[Cell] = []
    manifest: list[dict] = []
    with running_stub() as env:
        env["TF_IN_AUTOMATION"] = "1"
        env.pop("NODE_OPTIONS", None)
        for spec_path in spec_paths:
            spec = load_spec(spec_path)
            print("==> normaliser-parity: %s" % spec.id, flush=True)
            cells.extend(run_spec(normaliser, spec, spec_path.resolve(), env, keep,
                                  args.out, manifest))
    return summarise(cells)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
