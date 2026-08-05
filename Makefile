.PHONY: setup build-arms preflight check

# Install Python deps (aws-bench runner + dev tooling) via uv.
setup:
	uv sync

# Build every arm's Docker image, using the runner's own build-context
# convention: context = arms/<arm>/environment/ (the directory the
# aws-bench/Harbor runner actually builds from —
# harbor/environments/docker/docker.py context_dir=self.environment_dir),
# never the arm root. Tags match what each arm's own preflight.sh /
# README.md document (cdktn-bench/<arm>:dev), not an ad hoc scheme, so
# `make build-arms && make preflight` and each arm's own `./preflight.sh`
# operate on the exact same image.
#
# Fails loudly (exit 1) if an arm is missing its Dockerfile — a missing arm
# is a broken build, not something to skip past silently.
build-arms:
	@set -e; \
	missing=0; \
	for arm_dir in arms/*/; do \
		arm=$$(basename "$$arm_dir"); \
		dockerfile="$${arm_dir}environment/Dockerfile"; \
		if [ -f "$$dockerfile" ]; then \
			echo "==> building arm image: $$arm  (context: $${arm_dir}environment/)"; \
			docker build -t "cdktn-bench/$$arm:dev" -f "$$dockerfile" "$${arm_dir}environment"; \
		else \
			echo "==> ERROR: $$arm has no $$dockerfile" >&2; \
			missing=1; \
		fi; \
	done; \
	exit $$missing

# Run each arm image's REAL in-container preflight script under
# --network none, proving the toolchain (tsc/cdk synth, or terraform
# init+validate against the pre-warmed provider mirror) actually works
# offline — not a vacuous `true`. Entry point differs per arm (see each
# arm's own preflight.sh / DECISIONS.md "Agent-container baseline contract"
# for why they aren't unified onto one path yet). Fails loudly if an image
# is missing.
preflight:
	@set -e; \
	missing=0; \
	for arm_dir in arms/*/; do \
		arm=$$(basename "$$arm_dir"); \
		image="cdktn-bench/$$arm:dev"; \
		case "$$arm" in \
			hcl-raw) entrypoint=/opt/preflight/preflight.sh ;; \
			*) entrypoint=/usr/local/bin/preflight.sh ;; \
		esac; \
		if docker image inspect "$$image" >/dev/null 2>&1; then \
			echo "==> preflight: $$arm  ($$image, --network none, entrypoint $$entrypoint)"; \
			docker run --rm --network none --memory 4g --entrypoint "$$entrypoint" "$$image"; \
		else \
			echo "==> ERROR: $$image not built — run make build-arms" >&2; \
			missing=1; \
		fi; \
	done; \
	exit $$missing

# Repo-wide CI check, populated incrementally per slice (Slice E adds the
# oracle-equivalence CI + negative tests). Slice-added checks hook in via
# mk/*.mk (see include below) by extending the `check` target with
# double-colon rules or by appending to CHECKS.
check: $(CHECKS)
	./ci/check-smoke-drift.sh

# Per-slice make targets land in mk/<slice>.mk so concurrent slice workflows
# never edit this file. Missing dir is fine.
-include mk/*.mk
