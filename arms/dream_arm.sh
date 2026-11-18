#!/usr/bin/env bash
# Dream-RSI arm, following the paper's protocol per task:
#   E0 (starting policy)  ->  Dream-RSI round (learned policy)  vs  fixed-policy round (RFE)
# Grid 2 branches x 2 attempts = 4 Codex rollouts per round, ROUNDS=2 (E0 + 1),
# so each method spends 8 rollouts per task, matching Harness² at k=2.
#
#   bash arms/dream_arm.sh [TASK_ID ...]      # default: every task in bench/tasks.jsonl
set -euo pipefail
HP="$(cd "$(dirname "$0")/.." && pwd)"
BASH5="${BASH5:-$(command -v bash)}"   # needs bash >= 4 (macOS: brew install bash)
S="$HP/adapters/dream_rsi_swe/scripts"

export PYTHON="$HP/.venv-dream/bin/python"
export DRSI_EVAL_PYTHON="$HP/.venv-tests/bin/python"
# HP_AGENT=claude swaps the solver/improver for Claude Code via a codex-compatible shim.
if [ "${HP_AGENT:-codex}" = claude ]; then SHIM="$HP/agents/claude-shim"; W_DEFAULT="$HP/workspace/claude/dream"
else SHIM="$HP/agents/codex-shim"; W_DEFAULT="$HP/workspace/dream"; fi
export AGENT=codex CODEX_BIN="$SHIM" CODEX_MODEL=gpt-6-luna CODEX_EXEC_TIMEOUT_SEC=1800
export ROUNDS="${ROUNDS:-2}" BRANCHES="${BRANCHES:-2}" REFINE="${REFINE:-1}" MAX_WORKERS="${MAX_WORKERS:-2}" EVAL_TIMEOUT=900
TASKS_FILE="${HP_TASKS_FILE:-$HP/bench/tasks.jsonl}"

tasks=("$@")
if [ ${#tasks[@]} -eq 0 ]; then
  mapfile -t tasks < <("$DRSI_EVAL_PYTHON" -c "import json;[print(json.loads(l)['instance_id']) for l in open('$TASKS_FILE')]")
fi

for t in "${tasks[@]}"; do
  echo "=== $t"
  "$DRSI_EVAL_PYTHON" "$HP/adapters/dream_rsi_swe/make_task.py" "$t" >/dev/null
  W="${HP_DREAM_WS:-$W_DEFAULT}"
  [ -f "$W/e0/$t/live_cycle_manifest.json" ] || WORKSPACE="$W/e0/$t" "$BASH5" "$S/run_e0.sh" "$t"
  E0_WORKSPACE="$W/e0/$t" WORKSPACE="$W/dream_rsi/$t" "$BASH5" "$S/run_dream_rsi.sh" "$t" > "$W/$t.dream.log" 2>&1 &
  E0_WORKSPACE="$W/e0/$t" WORKSPACE="$W/baseline/$t" "$BASH5" "$S/run_baseline.sh" "$t" > "$W/$t.baseline.log" 2>&1 &
  wait
done
