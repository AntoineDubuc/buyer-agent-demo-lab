#!/usr/bin/env bash
# Run the demo lab: baseline = "before", each change folder = "after".
#
#   ./run_demo.sh [BASELINE_DIR C1_PACING_DIR C2_CREATIVES_DIR C3_NEGOTIATION_DIR] [OUT_DIR]
#
# BEFORE_ONLY=1 ./run_demo.sh  runs only the baseline and writes <change>.before-only.html.
#
# Defaults are the sibling folders of this repo. Each run uses that folder's own
# .venv/bin/python, a fresh throw-away SQLite database, and an EMPTY environment
# (env -i) plus only PATH, HOME, PYTHONPATH and DATABASE_URL: no credentials of
# any kind reach the run, and the lab blocks all network connections in-process.
set -euo pipefail

LAB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$LAB")"
BASE="${1:-$ROOT/buyer-agent}"
C1="${2:-$ROOT/buyer-agent-c1-pacing}"
C2="${3:-$ROOT/buyer-agent-c2-creatives}"
C3="${4:-$ROOT/buyer-agent-c3-negotiation}"
OUT="${5:-$ROOT/evidence/lab}"
mkdir -p "$OUT/results"

run_one() { # <buyer-agent-dir> <change> <label>
  local ba="$1" change="$2" label="$3" work
  work="$(mktemp -d "${TMPDIR:-/tmp}/demo-lab-run.XXXXXX")"
  if [[ ! -x "$ba/.venv/bin/python" ]]; then
    echo "!! $ba/.venv/bin/python not found; skipping $change/$label" >&2
    return 0
  fi
  echo "== $change ($label) using $ba"
  # cd into the throw-away folder so nothing is written into either repo
  # and no stray settings file is discovered from the working directory.
  (cd "$work" && env -i PATH="/usr/bin:/bin:/usr/sbin:/sbin" HOME="$HOME" \
      PYTHONPATH="$ba/src:$ba:$LAB" DATABASE_URL="sqlite:///$work/lab.db" \
      "$ba/.venv/bin/python" -m demo_lab.run --change "$change" --label "$label" \
      --out "$OUT/results/$(basename "$ba")" --buyer-agent-dir "$ba") || echo "!! run failed: $change/$label" >&2
}

declare -a PAIRS=("pacing:$C1" "creatives:$C2" "negotiation:$C3")
for pair in "${PAIRS[@]}"; do
  change="${pair%%:*}"; after_dir="${pair#*:}"
  run_one "$BASE" "$change" before
  before_json="$OUT/results/$(basename "$BASE")/$change.before.json"
  # The renderer is standard-library only; use the baseline interpreter.
  if [[ "${BEFORE_ONLY:-0}" == "1" ]]; then
    (cd "$LAB" && env -i PATH="/usr/bin:/bin" PYTHONPATH="$LAB" "$BASE/.venv/bin/python" -m demo_lab.report \
        --change "$change" --before "$before_json" --out "$OUT/$change.before-only.html")
    continue
  fi
  run_one "$after_dir" "$change" after
  (cd "$LAB" && env -i PATH="/usr/bin:/bin" PYTHONPATH="$LAB" "$BASE/.venv/bin/python" -m demo_lab.report \
      --change "$change" --before "$before_json" \
      --after "$OUT/results/$(basename "$after_dir")/$change.after.json" \
      --out "$OUT/$change.html")
done
echo "Evidence pages written to $OUT"
