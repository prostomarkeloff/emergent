.PHONY: test-full test-full-fast test-full-watch test-fuzz test-native test \
        test-light test-medium test-tough \
        lint format typecheck pyright pyright-path \
        ast-grep ast-grep-count ast-grep-rule ast-grep-path ast-grep-path-count \
        find-dup-defs find-dup-defs-calibrate lint-heavy verify green clean

# ════════════════════════════════════════════════════════════════════════════
# emergent — dev tasks: resident pytest-fast daemon, per-worktree isolation,
# lint gate. Library project — no DB / migrations.
# ════════════════════════════════════════════════════════════════════════════

# Per-worktree slug — isolates the pytest-fast socket between git worktrees so
# two `make test-full` runs never fight over one resident daemon (env-fingerprint
# mismatch → restart thrash). slug = basename + 6-char hash of the full path
# (basename alone can collide across two trees).
WT_PATH := $(shell git rev-parse --show-toplevel 2>/dev/null || pwd)
WT_HASH := $(shell printf '%s' "$(WT_PATH)" | shasum | cut -c1-6)
WT_SLUG := $(shell basename "$(WT_PATH)" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$$//' | cut -c1-40)
PYTEST_FAST_SOCK := /tmp/pytest-fast-$(WT_SLUG)-$(WT_HASH).sock

# Fast local defaults: light hypothesis profile (10 examples), schemathesis fuzz
# opted out (EMERGENT_FUZZ unset → tests/fuzz/ not collected). Override on the CLI:
#   HYPOTHESIS_PROFILE=tough make test-full       EMERGENT_FUZZ=1 make test-fuzz
export HYPOTHESIS_PROFILE ?= light

# Refingerprint the resident daemon on this env prefix, so flipping EMERGENT_FUZZ
# restarts it with a fresh collect instead of reusing the boot-time snapshot.
export PYTEST_FAST_ENV_PREFIXES := EMERGENT_

# Forward extra args to pytest:  make test PASS="tests/unit/test_x.py -k foo"
PASS ?=
PATH_ARG ?=
RULE ?=

# ─── Tests ───────────────────────────────────────────────────────────────────

# Canonical full run via the resident pytest-fast daemon (forkserver: warm
# collect once; first run boots ~3s, then warmup ≈ fork()). 600s idle, on a
# per-worktree socket. Schemathesis fuzz opted out (see test-fuzz). ~6s warm.
test-full:
	uv run pytest-fast --address $(PYTEST_FAST_SOCK) --ttl 600 --workers 6

# Muscle-memory alias.
test-full-fast: test-full

# Same + a background watcher that pre-warms a fresh daemon on src/test changes,
# so the first run after an edit is warm too.
test-full-watch:
	uv run pytest-fast --address $(PYTEST_FAST_SOCK) --ttl 600 --workers 6 --with-watcher

# Full suite INCLUDING schemathesis generative fuzz (heavy tier — 40-80s/test;
# CI / nightly, not the local loop).
test-fuzz:
	EMERGENT_FUZZ=1 uv run pytest-fast --address $(PYTEST_FAST_SOCK) --ttl 600 --workers 6

# Native pytest fallback — full reports + slowest-25 footer (no daemon, no fuzz).
test-native:
	uv run python -m pytest -q --durations=25 $(PASS)

# One file / -k expr:  make test PASS="tests/unit/test_x.py -k foo"
test:
	uv run python -m pytest -q $(PASS)

# Hypothesis-depth aliases (light=10 / medium=50 / tough=200 examples).
test-light:
	HYPOTHESIS_PROFILE=light  uv run pytest-fast --address $(PYTEST_FAST_SOCK) --ttl 600 --workers 6
test-medium:
	HYPOTHESIS_PROFILE=medium uv run pytest-fast --address $(PYTEST_FAST_SOCK) --ttl 600 --workers 6
test-tough:
	HYPOTHESIS_PROFILE=tough  uv run pytest-fast --address $(PYTEST_FAST_SOCK) --ttl 600 --workers 6

# ─── Lint / typecheck ──────────────────────────────────────────────────────────

# ast-grep ban-rules — project .ast-grep via sgconfig.yml (irreducible reflection
# ignored per-file in the rules; everything else fixed). GREEN.
ast-grep:
	uv run ast-grep scan emergent/

# Counts by rule (sorted).
ast-grep-count:
	@uv run ast-grep scan emergent/ 2>&1 | grep -E '^(error|warning)\[' | sed -E 's/\].*/]/' | sort | uniq -c | sort -rn

# Single rule:  make ast-grep-rule RULE=ban-getattr
ast-grep-rule:
	@test -n "$(RULE)" || (echo 'Usage: make ast-grep-rule RULE=<id>' && exit 1)
	uv run ast-grep scan --filter '^$(RULE)$$' emergent/

# Single subpath:  make ast-grep-path PATH_ARG=emergent/wire/compile/
ast-grep-path:
	@test -n "$(PATH_ARG)" || (echo 'Usage: make ast-grep-path PATH_ARG=<subpath>' && exit 1)
	uv run ast-grep scan $(PATH_ARG)

ast-grep-path-count:
	@test -n "$(PATH_ARG)" || (echo 'Usage: make ast-grep-path-count PATH_ARG=<subpath>' && exit 1)
	@uv run ast-grep scan $(PATH_ARG) 2>&1 | grep -E '^(error|warning)\[' | sed -E 's/\].*/]/' | sort | uniq -c | sort -rn

# Cross-file duplicate-definition gate (find-dup-defs via ohbin + committed
# find-dup-defs.directives). errors-only → CI gate. GREEN.
find-dup-defs:
	uv run ohbin run find-dup-defs -- emergent/ --only py -D @find-dup-defs.directives --errors-only

# find-dup-defs calibration + patternology — advisory histogram & helper
# candidates; never gates.
find-dup-defs-calibrate:
	uv run ohbin run find-dup-defs -- emergent/ --only py --patternology --calibrate

# ruff autofix (safe).
lint:
	uv run ruff check --fix emergent/ tests/

format:
	uv run ruff format emergent/

# pyright strict (see [tool.pyright]).
typecheck: pyright
pyright:
	uv run pyright emergent/

# pyright on a subpath:  make pyright-path PATH_ARG=emergent/wire/compile/
pyright-path:
	@test -n "$(PATH_ARG)" || (echo 'Usage: make pyright-path PATH_ARG=<subpath>' && exit 1)
	uv run pyright $(PATH_ARG)

# Full read-only gate — runs every checker, fails if any failed (does not stop at
# the first). ast-grep + find-dup-defs are green; ruff + pyright are advisory.
lint-heavy:
	@set +e; status=0; \
	echo "=== ast-grep ban-rules ==="; uv run ast-grep scan emergent/ || status=1; \
	echo ""; echo "=== find-dup-defs ==="; uv run ohbin run find-dup-defs -- emergent/ --only py -D @find-dup-defs.directives --errors-only || status=1; \
	echo ""; echo "=== ruff ==="; uv run ruff check emergent/ tests/ || status=1; \
	echo ""; echo "=== pyright (strict) ==="; uv run pyright emergent/ || status=1; \
	exit $$status

# ─── Composite ─────────────────────────────────────────────────────────────────

# verify: the green gates + the full suite — run after each change wave.
verify:
	$(MAKE) ast-grep
	$(MAKE) find-dup-defs
	$(MAKE) test-full

# green: THE gate. ast-grep (0) + find-dup-defs (0) + full suite, all must pass.
green:
	@set -e; \
	echo "=== ast-grep ==="; uv run ast-grep scan emergent/; \
	echo "=== find-dup-defs ==="; uv run ohbin run find-dup-defs -- emergent/ --only py -D @find-dup-defs.directives --errors-only; \
	echo "=== test-full ==="; uv run pytest-fast --address $(PYTEST_FAST_SOCK) --ttl 600 --workers 6

# ─── Clean ─────────────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
