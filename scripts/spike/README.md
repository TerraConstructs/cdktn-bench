# scripts/spike — M10 engine spike drivers

Evaluation harness for `docs/design/m10-one-rego-engine.md` §2: run every
existing Rego policy under OPA 1.19.0 and under `microsoft/regorus` 0.12.0 on
the same artifacts and diff the verdicts. Results:
`docs/design/m10-regorus-spike-results.md`.

Nothing here is wired into `make`, the generator, or any arm image. It touches
no graded row; it only reads specs, tasks and oracles and runs the toolchain
the falsifiability gate already runs.

```sh
docker build --platform linux/arm64 \
  -t cdktn-bench-spike/rego-engines:0.12.0 -f scripts/spike/Dockerfile scripts/spike

uv run python scripts/spike/collect_artifacts.py --out "$S/artifacts" --work-dir "$S/work"
uv run python scripts/spike/run_comparison.py   --artifacts "$S/artifacts" --out "$S/cmp"
```

`collect_artifacts.py` runs `terraform plan` / `cdk synth` per fixture and is
the slow half (~30 s each, serial). `run_comparison.py` copies the artifacts
into one container (colima does not share `/private/tmp`, so `docker cp`, not a
bind mount) and drives `compare_engines.sh`. `probes.sh` records the behaviours
the pair table cannot show: coverage, undefined query, unparseable policy,
builtin error.
