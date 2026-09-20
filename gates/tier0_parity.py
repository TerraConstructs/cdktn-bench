#!/usr/bin/env python3
"""All-artifacts tier-0 parity gate: the retired bash library vs the Python
driver that replaced it, with the Rego backend as an opt-in third column.

Grade every artifact a spec's fixtures produce with both graders -- the
`assert_check` bash function as it stood before DECISIONS.md Amendment 43,
recovered from git rather than from the working tree, and the generated
tests/{tier0,ops}.py -- and require the same three-valued outcome per assert
and the same `tier0_pass`. The landing condition for the driver, and an
ON-DEMAND cross-check after it, never a `make ci` gate: only artifacts that
exist are graded, so a divergence no fixture value reaches is invisible here
and is pinned per column in oracles/tests/test_op_parity.py instead.

Two divergences are known, and named in the summary rather than tolerated
silently: the regex ops move from jq's Oniguruma to Python `re`, and jq's
`index` read `in` as a subsequence test over a doubly-nested node. `--rego`
adds generator/jsonpath_rego.py as a third column, compiling a policy into
scratch for a task dir that ships no tests/tier0.rego.

Exit 0 = every graded cell agrees. 1 = a divergence, or an artifact that could
not be graded at all. 3 = nothing was gradeable, the repo's NOT_AUTHORED
convention, so a caller can keep that non-gating without reading it as a pass.

Usage: a spec path, `--all`, or `--regrade DIR` over a tree `--out` kept; the
rest is docs/gates.md#tier0-parity.
"""

from __future__ import annotations

import argparse
import ast
import json
import shlex
import subprocess
import sys
import tempfile
import textwrap
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
    """One (spec, arm, fixture) artifact graded by every enabled column."""

    label: str
    spec_id: str
    arm: str
    fixture: str
    asserts: int = 0
    bash_pass: int | None = None
    driver_pass: int | None = None
    rego_pass: int | None = None
    # (assert name, op, bash outcome, driver outcome) for every regex assert
    # graded here: the flavour change from Oniguruma to Python `re` is the one
    # deliberate divergence surface, so it is reported rather than assumed.
    regex_rows: list[tuple[str, str, str, str]] = field(default_factory=list)
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
            f"tier0_pass={self.driver_pass} on every column"
        )


# The bash library the driver replaced. Recovered from git, never from the
# working tree: a copy edited into the tree alongside the driver would make
# this gate compare the driver against itself.
def baseline_assert_lib(rev: str, scratch: Path) -> Path:
    """`ASSERT_LIB_SH` out of `<rev>:generator/gen.py`, written to a file.

    Read with `ast` rather than by importing that revision's module, which
    would pull in the whole generator's imports. Walks back through gen.py's
    own history when `rev` no longer defines the symbol, so the gate keeps
    working after the removal is committed.
    """
    for candidate in _revs_to_try(rev):
        source = subprocess.run(
            ["git", "show", f"{candidate}:generator/gen.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        if source.returncode != 0:
            continue
        literal = _assert_lib_literal(source.stdout)
        if literal is None:
            continue
        scratch.mkdir(parents=True, exist_ok=True)
        path = scratch / "_assert_lib.sh"
        path.write_text(literal)
        return path
    raise RuntimeError(
        f"no revision reachable from {rev!r} defines ASSERT_LIB_SH in "
        "generator/gen.py, so the retired bash grader cannot be recovered"
    )


def _revs_to_try(rev: str) -> list[str]:
    log = subprocess.run(
        ["git", "log", "--format=%H", "-40", rev, "--", "generator/gen.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    return [rev] + [line for line in log.stdout.split() if line]


def _assert_lib_literal(source: str) -> str | None:
    """The dedented value of a module-level `ASSERT_LIB_SH = textwrap.dedent(
    "...")` assignment, or None if that revision has no such assignment."""
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "ASSERT_LIB_SH" for t in node.targets
        ):
            continue
        value = node.value
        if isinstance(value, ast.Call) and value.args:
            value = value.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return textwrap.dedent(value.value)
    return None


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


def grade_bash(
    assert_lib: Path, asserts: list[tuple[str, str, str, object]], artifact: Path
) -> dict[str, str]:
    """Outcomes from the retired `assert_check`, one call per assert -- the
    grader every trial ran before the driver, sourced rather than
    reimplemented."""
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


def grade_driver(
    ops_py: Path, asserts: list[tuple[str, str, str, object]], artifact: Path
) -> dict[str, str]:
    """Outcomes from the task's own generated tests/ops.py, one `--one` call
    per assert -- the shipped grader, not a host-side reimplementation of it."""
    out: dict[str, str] = {}
    for name, jsonpath, op, expected in asserts:
        proc = subprocess.run(
            [
                sys.executable, str(ops_py), "--one", name,
                jsonpath_to_jq(jsonpath), op, json.dumps(expected), str(artifact),
            ],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode not in _BY_RC:
            raise RuntimeError(
                f"ops.py returned {proc.returncode} for {name!r}, outside the "
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
    scratch: Path, assert_lib: Path, with_rego: bool = False,
) -> Cell:
    cell = Cell(label=label, spec_id=spec.id, arm=ARM_DIRNAME[arm], fixture=fixture)
    asserts = tier0_asserts(spec, arm, step)
    cell.asserts = len(asserts)
    bash = grade_bash(assert_lib, asserts, artifact)
    driver = grade_driver(tests / "ops.py", asserts, artifact)
    columns = {"bash": bash, "driver": driver}
    if with_rego:
        policy = tier0_policy(spec, arm, step, tests, scratch)
        rego, cell.rego_pass = grade_rego(policy, tier0_rego_pkg(spec), artifact)
        columns["rego"] = rego
    # Every column derives the verdict the same way: every applicable assert
    # held. The shell path starts `tier0_pass=1` and lets each non-zero assert
    # drop it, so an arm with no tier-0 assert passes tier 0.
    cell.bash_pass = 1 if all(v == HELD for v in bash.values()) else 0
    cell.driver_pass = 1 if all(v == HELD for v in driver.values()) else 0
    for name, _jsonpath, op, _expected in asserts:
        if op in ("regex", "not_regex"):
            cell.regex_rows.append(
                (name, op, bash.get(name, "?"), driver.get(name, "?"))
            )
    # Both directions: an assert only one column knows about would otherwise
    # show up nowhere, since neither the per-assert comparison below nor
    # `tier0_pass` moves for it.
    for this, that in ((a, b) for a in columns for b in columns if a != b):
        extra = sorted(set(columns[this]) - set(columns[that]))
        if extra:
            cell.divergences.append(
                f"the {that} column reports no outcome for {extra} -- the "
                "columns were compiled from different assert sets"
            )
    for name in bash:
        reached = {
            col: outcomes[name] for col, outcomes in columns.items() if name in outcomes
        }
        if len(set(reached.values())) > 1:
            rendered = " ".join(f"{col}={outcome}" for col, outcome in reached.items())
            cell.divergences.append(f"{name}: {rendered}")
    if cell.bash_pass != cell.driver_pass:
        cell.divergences.append(
            f"tier0_pass: bash={cell.bash_pass} driver={cell.driver_pass}"
        )
    if with_rego and cell.driver_pass != cell.rego_pass:
        cell.divergences.append(
            f"tier0_pass: driver={cell.driver_pass} rego={cell.rego_pass}"
        )
    return cell


# ---------------------------------------------------------------------------
# collect (expensive) and regrade (cheap)
# ---------------------------------------------------------------------------


def run_spec(spec: Spec, spec_path: Path, env: dict[str, str], keep: ac.KeptTempDir,
             out: Path | None, manifest: list[dict], assert_lib: Path,
             with_rego: bool) -> list[Cell]:
    cells: list[Cell] = []
    for c in ac.collect(spec, env, keep, require_tests=("ops.py", "tier0.py")):
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
                              scratch=(c.workdir or c.plan.parent) / "tier0-parity",
                              assert_lib=assert_lib, with_rego=with_rego)
        except (RuntimeError, ValueError, OSError) as exc:
            cell = Cell(label=c.label, spec_id=spec.id, arm=ARM_DIRNAME[c.arm],
                        fixture=c.fixture)
            cell.divergences.append(f"could not grade with every column: {exc}")
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


def regrade(tree: Path, assert_lib: Path, with_rego: bool) -> list[Cell]:
    """Re-grade a tree `--out` wrote, with no toolchain: the graders are read
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
                assert_lib=assert_lib, with_rego=with_rego,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            cell = Cell(label=row["label"], spec_id=spec.id, arm=row["arm"],
                        fixture=row["fixture"])
            cell.divergences.append(f"could not grade with every column: {exc}")
        cells.append(cell)
        print(f"  {cell.render()}", flush=True)
    return cells


def summarise(cells: list[Cell], with_rego: bool) -> int:
    graded = [c for c in cells if not c.note]
    bad = [c for c in cells if c.divergences]
    skipped = [c for c in cells if c.note]
    columns = "bash vs driver" + (" vs rego" if with_rego else "")
    print("")
    print(f"=== tier0-parity: tier-0 {columns}, per spec/arm/fixture ===")
    for c in cells:
        print(c.render())
    # The regex ops are the flavour change this migration makes, so their
    # verdicts are listed rather than merely found non-divergent: a reader has
    # to be able to see WHICH asserts crossed from Oniguruma to Python `re` and
    # what each one came out as under both.
    regex_rows = [(c.label, *row) for c in graded for row in c.regex_rows]
    print("")
    print(f"=== regex/not_regex asserts graded ({len(regex_rows)}) ===")
    for label, name, op, bash, driver in regex_rows:
        flag = "OK  " if bash == driver else "DIFF"
        print(f"  {flag} {label} {name} ({op}): bash={bash} driver={driver}")
    if not regex_rows:
        print("  (none reached by a fixture artifact)")
    print("")
    print(
        f"graded {len(graded)} artifact(s), "
        f"{sum(c.asserts for c in graded)} assert evaluation(s) per column; "
        f"{len(skipped)} skipped, {len(bad)} divergent"
    )
    if bad:
        print("tier0-parity: FAILED -- the tier-0 columns disagree", file=sys.stderr)
        return 1
    if not graded:
        print("tier0-parity: NOT_AUTHORED -- no fixture produced a gradeable artifact")
        return 3
    print("tier0-parity: OK -- every column agrees on every graded artifact")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec", nargs="?", type=Path)
    ap.add_argument("--all", action="store_true", help="every specs/*.yaml")
    ap.add_argument("--out", type=Path, help="keep the collected artifacts here")
    ap.add_argument("--work-dir", type=Path, help="keep each fixture's working copy here")
    ap.add_argument("--regrade", type=Path, help="re-grade a tree --out wrote; runs no toolchain")
    ap.add_argument(
        "--baseline-rev", default="HEAD",
        help="revision to recover the retired assert_check bash library from",
    )
    ap.add_argument(
        "--rego", action="store_true",
        help="also grade with the compiled tier-0 Rego (available, not adopted)",
    )
    args = ap.parse_args(argv)

    if args.regrade:
        lib = baseline_assert_lib(args.baseline_rev, args.regrade / "tier0-baseline")
        return summarise(regrade(args.regrade, lib, args.rego), args.rego)

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
    lib = baseline_assert_lib(args.baseline_rev, work / "tier0-baseline")

    cells: list[Cell] = []
    manifest: list[dict] = []
    with running_stub() as env:
        env["TF_IN_AUTOMATION"] = "1"
        env.pop("NODE_OPTIONS", None)
        for spec_path in spec_paths:
            spec = load_spec(spec_path)
            print(f"==> tier0-parity: {spec.id}", flush=True)
            cells.extend(run_spec(spec, spec_path.resolve(), env, keep, args.out,
                                  manifest, lib, args.rego))
    return summarise(cells, args.rego)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
