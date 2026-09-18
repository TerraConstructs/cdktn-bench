#!/usr/bin/env python3
"""All-artifacts tier-0 parity gate: the jq backend vs the Rego one.

Grade every artifact a spec's fixtures produce with BOTH tier-0 backends --
generator/jsonpath_jq.py compiled into the generated tests/_assert_lib.sh, and
generator/jsonpath_rego.py compiled from the same spec entries -- and require
the same three-valued outcome per assert and the same `tier0_pass`. This is an
ON-DEMAND cross-check, not a `make ci` gate: jq is the shipped grader
(DECISIONS.md Amendment 42), so nothing here can block a commit, and it grades
only the artifacts that exist -- a divergence reachable solely through a value
no fixture produces is invisible to it. Those values are pinned column by
column in oracles/tests/test_op_parity.py; docs/gates.md#tier0-parity has the
rest.

Any spec can be graded, whatever its `oracle.tier0_engine` says: a task dir
that ships no tests/tier0.rego (every jq spec, i.e. all of them today) has one
compiled into the run's scratch directory here.

Exit 0 = every graded cell agrees. 1 = a divergence, or an artifact that could
not be graded at all. 3 = nothing was gradeable, the repo's NOT_AUTHORED
convention, so a caller can keep that non-gating without reading it as a pass.

Usage: a spec path, `--all`, or `--regrade DIR` over a tree `--out` kept.
"""

from __future__ import annotations

import argparse
import json
import shlex
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
from gen import ARM_DIRNAME, build_tier0_rego_file, tier0_rego_pkg  # noqa: E402
from jsonpath_jq import jsonpath_to_jq  # noqa: E402
from spec_model import Arm, Spec, load_spec  # noqa: E402

HELD, CONTRADICTED, UNRESOLVABLE = "held", "contradicted", "unresolvable"
_BY_RC = {0: HELD, 1: CONTRADICTED, 2: UNRESOLVABLE}


@dataclass
class Cell:
    """One (spec, arm, fixture) artifact graded by both backends."""

    label: str
    spec_id: str
    arm: str
    fixture: str
    asserts: int = 0
    jq_pass: int | None = None
    rego_pass: int | None = None
    divergences: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def ok(self) -> bool:
        return not self.divergences and not self.note

    def render(self) -> str:
        if self.note:
            return f"[{'SKIP' if self.note.startswith('NO_ARTIFACT') else 'FAIL'}] {self.label}: {self.note}"
        if self.divergences:
            return f"[FAIL] {self.label}:\n" + "\n".join(f"        {d}" for d in self.divergences)
        return (
            f"[PASS] {self.label}: {self.asserts} assert(s) agree, "
            f"tier0_pass={self.jq_pass} on both backends"
        )


def tier0_asserts(spec: Spec, arm: Arm, step) -> list[tuple[str, str, str, object]]:
    """The tier-"0" asserts this arm (and, for a multi-step task, this step)
    grades, as `(name, jsonpath, op, expected)` -- the same projection
    generator/gen.py applies when it emits both backends."""
    names = None if step is None else set(spec.step_assert_names(step))
    out = []
    for a in spec.oracle.structural_asserts:
        if names is not None and a.name not in names:
            continue
        if arm not in a.applies_to or a.tier != "0":
            continue
        jsonpath = a.cfn_jsonpath if arm == "awscdk" else a.tf_jsonpath
        out.append((a.name, jsonpath, a.op, a.expected))
    return out


def grade_jq(
    assert_lib: Path, asserts: list[tuple[str, str, str, object]], artifact: Path
) -> dict[str, str]:
    """Outcomes from the REAL generated `assert_check`, one call per assert.

    The generated tests/_assert_lib.sh is sourced rather than reimplemented, so
    this column is the grader a trial runs today and there is no third
    implementation of the op table to keep in sync.
    """
    out: dict[str, str] = {}
    for name, jsonpath, op, expected in asserts:
        script = (
            "set -uo pipefail\n"
            f"source {shlex.quote(str(assert_lib))}\n"
            f"assert_check {shlex.quote(name)} {shlex.quote(jsonpath_to_jq(jsonpath))} "
            f"{shlex.quote(op)} {shlex.quote(json.dumps(expected))} "
            f"{shlex.quote(str(artifact))}\n"
        )
        proc = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=False
        )
        if proc.returncode not in _BY_RC:
            raise RuntimeError(
                f"assert_check returned {proc.returncode} for {name!r}, outside the "
                f"three-valued contract: {proc.stdout}{proc.stderr}"
            )
        out[name] = _BY_RC[proc.returncode]
    return out


def tier0_policy(spec: Spec, arm: Arm, step, tests: Path, scratch: Path) -> Path:
    """The tests/tier0.rego to grade with: the task's own when the spec ships
    one, otherwise the same bytes compiled into `scratch`.

    Only an `oracle.tier0_engine: rego` spec ships the file, and no spec does
    today, so this cross-check compiles what it needs rather than requiring a
    corpus-wide emission it would be the sole consumer of. The repo is never
    written to.
    """
    shipped = tests / "tier0.rego"
    if shipped.exists():
        return shipped
    scratch.mkdir(parents=True, exist_ok=True)
    compiled = scratch / "tier0.rego"
    compiled.write_text(build_tier0_rego_file(spec, arm, step))
    return compiled


def grade_rego(policy: Path, pkg: str, artifact: Path) -> tuple[dict[str, str], int]:
    """Outcomes and `tier0_pass` from one `opa eval` of the compiled
    tests/tier0.rego -- the same file and the same query a generated
    static_tiers.sh evaluates under `oracle.tier0_engine: rego`."""
    proc = subprocess.run(
        ["opa", "eval", "-f", "json", "-I", "-d", str(policy),
         f"data.cdktn_bench.{pkg}.tier0"],
        stdin=artifact.open("rb"), capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"opa eval failed on {policy}: {proc.stderr.strip()}")
    value = json.loads(proc.stdout)["result"][0]["expressions"][0]["value"]
    outcomes: dict[str, str] = {}
    for cls in (HELD, CONTRADICTED, UNRESOLVABLE):
        for name in value.get(cls, []):
            if name in outcomes:
                raise RuntimeError(
                    f"{name!r} landed in both {outcomes[name]} and {cls}: the three "
                    "verdict classes must be disjoint per assert"
                )
            outcomes[name] = cls
    return outcomes, int(value.get("tier0_pass", 0))


def grade_cell(
    spec: Spec, arm: Arm, step, label: str, fixture: str, tests: Path, artifact: Path,
    scratch: Path,
) -> Cell:
    cell = Cell(label=label, spec_id=spec.id, arm=ARM_DIRNAME[arm], fixture=fixture)
    asserts = tier0_asserts(spec, arm, step)
    cell.asserts = len(asserts)
    jq = grade_jq(tests / "_assert_lib.sh", asserts, artifact)
    policy = tier0_policy(spec, arm, step, tests, scratch)
    rego, rego_pass = grade_rego(policy, tier0_rego_pkg(spec), artifact)
    cell.rego_pass = rego_pass
    # Both backends derive the verdict the same way: every applicable assert
    # held. The jq path starts `tier0_pass=1` and lets each non-zero
    # assert_check drop it, so an arm with no tier-0 assert passes tier 0.
    cell.jq_pass = 1 if all(v == HELD for v in jq.values()) else 0
    # Both directions: an assert only one backend knows about would otherwise
    # show up nowhere, since neither the per-assert comparison below nor
    # `tier0_pass` moves for it.
    for side, other, where in (
        (jq, rego, "the compiled tier-0 Rego"), (rego, jq, "the jq assert calls"),
    ):
        extra = sorted(set(side) - set(other))
        if extra:
            cell.divergences.append(
                f"{where} reports no outcome for {extra} -- the two backends "
                "were compiled from different assert sets"
            )
    for name in jq:
        if name in rego and jq[name] != rego[name]:
            cell.divergences.append(f"{name}: jq={jq[name]} rego={rego[name]}")
    if cell.jq_pass != cell.rego_pass:
        cell.divergences.append(
            f"tier0_pass: jq={cell.jq_pass} rego={cell.rego_pass}"
        )
    return cell


# ---------------------------------------------------------------------------
# collect (expensive) and regrade (cheap)
# ---------------------------------------------------------------------------


def run_spec(spec: Spec, spec_path: Path, env: dict[str, str], keep: ac.KeptTempDir,
             out: Path | None, manifest: list[dict]) -> list[Cell]:
    cells: list[Cell] = []
    for c in ac.collect(spec, env, keep, require_tests=("_assert_lib.sh",)):
        if c.plan is None:
            cells.append(Cell(label=c.label, spec_id=spec.id, arm=ARM_DIRNAME[c.arm],
                              fixture=c.fixture,
                              note=f"NO_ARTIFACT (toolchain produced none; reward={c.reward})"))
            continue
        # A grader that ABORTS is a failure of this gate, not of the run: one
        # unparseable artifact or one uncompilable policy must not throw away
        # the several hours of collection the other fixtures cost.
        try:
            cell = grade_cell(spec, c.arm, c.step, c.label, c.fixture, c.tests, c.plan,
                              scratch=(c.workdir or c.plan.parent) / "tier0-parity")
        except (RuntimeError, ValueError, OSError) as exc:
            cell = Cell(label=c.label, spec_id=spec.id, arm=ARM_DIRNAME[c.arm],
                        fixture=c.fixture)
            cell.divergences.append(f"could not grade with both backends: {exc}")
        cells.append(cell)
        if out is not None:
            dest = out / f"{cell.label.replace('/', '__')}.json"
            dest.write_bytes(c.plan.read_bytes())
            manifest.append({
                "label": c.label, "spec": str(spec_path.relative_to(REPO_ROOT)),
                "arm": c.arm, "fixture": c.fixture,
                "step": c.step.name if c.step else None,
                "tests": str(c.tests.relative_to(REPO_ROOT)),
                "artifact": dest.name, "reward": c.reward, "seconds": c.seconds,
            })
            (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(f"  {cell.render()}", flush=True)
    return cells


def regrade(tree: Path) -> list[Cell]:
    """Re-grade a tree `--out` wrote, with no toolchain: the compilers are read
    from the working copy, the artifacts from disk."""
    manifest = json.loads((tree / "manifest.json").read_text())
    cells: list[Cell] = []
    for row in manifest:
        spec = load_spec(REPO_ROOT / row["spec"])
        step = None
        if row["step"] is not None:
            step = next(s for s in (spec.steps or []) if s.name == row["step"])
        try:
            cell = grade_cell(
                spec, row["arm"], step, row["label"], row["fixture"],
                REPO_ROOT / row["tests"], tree / row["artifact"],
                scratch=tree / "tier0-rego" / row["label"].replace("/", "__"),
            )
        except (RuntimeError, ValueError, OSError) as exc:
            cell = Cell(label=row["label"], spec_id=spec.id, arm=row["arm"],
                        fixture=row["fixture"])
            cell.divergences.append(f"could not grade with both backends: {exc}")
        cells.append(cell)
        print(f"  {cell.render()}", flush=True)
    return cells


def summarise(cells: list[Cell]) -> int:
    graded = [c for c in cells if not c.note]
    bad = [c for c in cells if c.divergences]
    skipped = [c for c in cells if c.note]
    print("")
    print("=== tier0-parity: tier-0 jq vs rego, per spec/arm/fixture ===")
    for c in cells:
        print(c.render())
    print("")
    print(
        f"graded {len(graded)} artifact(s), "
        f"{sum(c.asserts for c in graded)} assert evaluation(s) per backend; "
        f"{len(skipped)} skipped, {len(bad)} divergent"
    )
    if bad:
        print("tier0-parity: FAILED -- the two tier-0 backends disagree", file=sys.stderr)
        return 1
    if not graded:
        print("tier0-parity: NOT_AUTHORED -- no fixture produced a gradeable artifact")
        return 3
    print("tier0-parity: OK -- both tier-0 backends agree on every graded artifact")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec", nargs="?", type=Path)
    ap.add_argument("--all", action="store_true", help="every specs/*.yaml")
    ap.add_argument("--out", type=Path, help="keep the collected artifacts here")
    ap.add_argument("--work-dir", type=Path, help="keep each fixture's working copy here")
    ap.add_argument("--regrade", type=Path, help="re-grade a tree --out wrote; runs no toolchain")
    args = ap.parse_args(argv)

    if args.regrade:
        return summarise(regrade(args.regrade))

    if args.all:
        spec_paths = [
            p for p in sorted(REPO_ROOT.glob("specs/*.yaml")) if p.name != "split.yaml"
        ]
    elif args.spec:
        spec_paths = [args.spec]
    else:
        ap.error("pass a spec path, --all, or --regrade DIR")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    fallback = Path(tempfile.gettempdir()) / "tier0-parity-work"
    work = args.work_dir or (args.out / "work" if args.out else fallback)
    keep = ac.install(work)

    cells: list[Cell] = []
    manifest: list[dict] = []
    with running_stub() as env:
        env["TF_IN_AUTOMATION"] = "1"
        env.pop("NODE_OPTIONS", None)
        for spec_path in spec_paths:
            spec = load_spec(spec_path)
            print(f"==> tier0-parity: {spec.id}", flush=True)
            cells.extend(run_spec(spec, spec_path.resolve(), env, keep, args.out, manifest))
    return summarise(cells)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
