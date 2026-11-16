#!/usr/bin/env bash
# Run every arm on the validated tasks, then print the results table.
#   bash run.sh            # all arms (≈280 Codex sessions; mind your Codex quota)
#   bash run.sh compare    # only rebuild the table from existing runs
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" != compare ]; then
  .venv-tests/bin/python arms/single.py
  bash arms/dream_arm.sh
  .venv-h2/bin/python arms/harness2_arm.py --k 2
fi
.venv-tests/bin/python compare.py
