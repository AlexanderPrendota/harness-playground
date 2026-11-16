# Dream-RSI launch scripts, extended with SWE-rebench tasks.
# run_*.sh here are symlinks to the pinned vendor scripts; they source this file, which
# sources the vendor common.sh unchanged and overrides only task selection and preflight.
HP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$HP_ROOT/vendor/dream-rsi/scripts/common.sh"

eval "vendor_$(declare -f select_task)"
eval "vendor_$(declare -f preflight)"

select_task() {
  case "$1" in
    *__*-[0-9]*)
      TASK="$1" TASK_KIND=swe ROUNDS_DEFAULT=2 EVAL_TIMEOUT_DEFAULT=900
      TASK_DIR="$HP_ROOT/workspace/dream_tasks/$TASK"
      PROBLEM="$TASK_DIR/$TASK.txt"
      INIT_PROGRAM="$TASK_DIR/init_program.py"
      EVALUATOR="$TASK_DIR/evaluator.py"
      EXPLORE_PROMPT="$REPO_ROOT/dream_rsi/prompts/explore.txt"
      [ -f "$INIT_PROGRAM" ] || die "run: python adapters/dream_rsi_swe/make_task.py $TASK"
      ;;
    *) vendor_select_task "$1" ;;
  esac
}

preflight() {
  if [ "$TASK_KIND" = swe ]; then
    local f
    for f in "$PROBLEM" "$EVALUATOR" "$INIT_PROGRAM" "$EXPLORE_PROMPT"; do
      [ -f "$f" ] || die "missing file: $f"
    done
  else
    vendor_preflight
  fi
}

# The vendor check rejects a round where no attempt scored above 0, as a sign of a broken
# agent or evaluator. On SWE tasks an all-zero round is a legitimate outcome (the bug was
# not fixed), so for them only require that every attempt was evaluated.
eval "vendor_$(declare -f check_round_complete)"
check_round_complete() {
  if [ "${TASK_KIND:-}" != swe ]; then vendor_check_round_complete "$@"; return; fi
  "$PYTHON" - "$1" <<'PY'
import json, sys
nodes = json.load(open(sys.argv[1], encoding="utf-8")).get("nodes") or []
raws = [n.get("raw") or {} for n in nodes]
if not nodes or sum(1 for r in raws if r.get("evaluated")) < len(nodes):
    sys.exit(f"{sys.argv[1]}: not every node was evaluated")
best = max(float(r.get("combined_score") or 0) for r in raws)
print(f"{len(nodes)} nodes, best score {best:.6g}")
PY
}
