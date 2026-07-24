#!/usr/bin/env bash
#
# blipsmith verify gate. Every step runs even after an earlier one fails, so the
# summary shows the whole picture rather than just the first breakage. Exit code
# is nonzero if any step failed.
#
# Steps not yet buildable are reported as `skip` with the item that lands them.
# A skip never turns the gate green on its own and never hides a failure.

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "verify: uv is required but not on PATH. Install it: https://docs.astral.sh/uv/" >&2
  exit 2
fi

STEP_NAMES=()
STEP_RESULTS=()
FAILED=0

banner() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

record() {
  STEP_NAMES+=("$1")
  STEP_RESULTS+=("$2")
  [ "$2" = "FAIL" ] && FAILED=1
  return 0
}

run_step() {
  local name="$1"
  shift
  banner "$name"
  if "$@"; then record "$name" "pass"; else record "$name" "FAIL"; fi
}

skip_step() {
  banner "$1"
  echo "not yet implemented ($2)"
  record "$1" "skip"
}

native_build() {
  rm -rf build
  uv sync --reinstall-package blipsmith
}

lint() {
  uv run ruff check . && uv run ruff format --check .
}

has_module() {
  uv run python -c "
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec('$1') else 1)
" >/dev/null 2>&1
}

run_step "native core build (clean)" native_build
run_step "lint (ruff)" lint
run_step "typecheck (mypy)" uv run mypy
run_step "tests (pytest)" uv run pytest
run_step "determinism: no libm transcendentals" uv run python scripts/check_no_libm.py

if has_module blipsmith.cli; then
  run_step "CLI boot" uv run blipsmith --help
else
  skip_step "CLI boot" "lands in B11"
fi

if has_module blipsmith.mcp_server; then
  run_step "MCP server boot" uv run python -m blipsmith.mcp_server --boot-check
else
  skip_step "MCP server boot" "lands in B12"
fi

banner "verify summary"
for i in "${!STEP_NAMES[@]}"; do
  printf '  %-6s %s\n' "${STEP_RESULTS[$i]}" "${STEP_NAMES[$i]}"
done

if [ "$FAILED" -ne 0 ]; then
  echo -e "\nverify: FAILED"
  exit 1
fi

echo -e "\nverify: green"
