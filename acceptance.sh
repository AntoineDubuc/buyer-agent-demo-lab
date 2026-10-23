#!/usr/bin/env bash
# Pass/fail acceptance check for one buyer-agent checkout.
#
#   ./acceptance.sh <path-to-buyer-agent-checkout> <pacing|creatives|negotiation|all> [--out DIR]
#
# Prints one PASS/FAIL line per criterion. Exit 0 only if every criterion passes.
set -euo pipefail
if [[ $# -lt 2 ]]; then
  echo "usage: $0 <path-to-buyer-agent-checkout> <pacing|creatives|negotiation|all> [--out DIR]" >&2
  exit 2
fi
LAB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The checker is standard library only (Python 3.11+). Use the checkout's own
# interpreter when it exists, so no other Python is needed.
PY="$1/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
exec env -i PATH="/usr/bin:/bin:/usr/sbin:/sbin" HOME="$HOME" PYTHONPATH="$LAB" "$PY" -m demo_lab.check "$@"
